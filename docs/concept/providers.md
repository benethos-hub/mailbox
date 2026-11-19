# Concept: providers

Part of the [concept](../CONCEPT.md): sections 5 to 5.7.

## 5. Provider adapters and libraries

Every adapter implements `Reads` of `data.providers.base`, and of the
protocols beyond it those it may be able to do: `Writes` (flags and
folders), `Deletes`, `Drafts`, `Sends`, `Watches` (push), `Deltas`
(changes since a token), `FlagChanges` (whose flags changed, IMAP
with CONDSTORE), `Threads` (threads the server keeps), `Summaries`
(messages read by id, for threads the index keeps) and `Places` (the
folders of messages read by id without their content, for a change
under grants that name folders where no index keeps them). One protocol per ability, checked with
`isinstance`, was **decided 2026-10-07**. What an account can do follows
from what its server answers (5.11, R4): asked when the account is
connected or verified, when the sync sees a folder come or go, and when
the server refuses what was stored. The capabilities and the marks the
account reads and writes are stored with it. The domain checks what each
operation needs before it calls the adapter, the same way for every
account, and answers `501 not_supported` for a lack.
`GET /v1/accounts/{id}` and `/v1/me` list them, so a client can tell in
advance. The UI offers no action an account cannot do, and the MCP
server's `list_accounts` names what an account lacks.

| Adapter | Covers | Library | Licence | Notes |
|---|---|---|---|---|
| `imap` | everything without a better API: GMX, web.de, T-Online, Yahoo, AOL, iCloud, Posteo, mailbox.org, IONOS, Strato, Zoho, own servers, Proton via Bridge | **IMAPClient** (protocol), the mail parser of **imap-tools** (messages) | BSD-3-Clause, Apache-2.0 | synchronous, run in a worker thread. Auth: password and app password, built. **XOAUTH2** waits for the token refresher (5.1) |
| `smtp` | sending for `imap` and `pop3` accounts | stdlib **smtplib**, for now (decided 2026-09-24) | PSF | synchronous, run in a worker thread like IMAP, also XOAUTH2, built |
| `microsoft` | Microsoft 365, Outlook.com | Microsoft Graph over **httpx** | — | OAuth 2.0, the only sensible route (5.4), built |
| `gmail` | Gmail, Google Workspace | Gmail REST API over **httpx** | — | OAuth 2.0 with a Google client of the deployment's own, no Google SDK (5.5), built |
| `jmap` | Fastmail, Stalwart, Cyrus, any JMAP server | JMAP (RFC 8620/8621) over **httpx** | — | password or API token. A second generic protocol next to IMAP (5.6), built |
| `pop3` | legacy mailboxes | stdlib **poplib** | PSF | synchronous, worker thread, reduced (5.2), built |
| `memory` | tests and development | — | — | built |

### 5.1 IMAP: IMAPClient for the protocol, imap-tools for parsing

**Decided 2026-09-24:** the protocol goes through **IMAPClient**, in
`data/protocols/imap/`. It parses every server answer and returns
any FETCH item as a dict, which the sync (4.1) and phase 2 (`COPYUID`,
`MOVE`, `QRESYNC`) need. Phase 1b started on imap-tools. It offered
nothing for fetching only the `Message-ID` header, so raw `imaplib`
answers had to be parsed by hand.

Fetched messages are parsed by the mail parser of **imap-tools**, in
`data/mail/parse.py`, shared by every adapter that sees raw messages:
subject, addresses, dates, text and HTML with broken charsets,
attachments. It saves writing a MIME parser. Replacing it, e.g. with the
standard library's `email`, rewrites that one module.

Both are **synchronous**, while the API is async. Solution: one connection
per account, owned by the adapter, guarded by a lock, every call run via
`anyio.to_thread.run_sync`. IMAP connections are
stateful (selected folder) and per account anyway, so this costs little.

The alternative is **aioimaplib** (async, but raw responses with no
parsing). The adapter boundary keeps the choice reversible: if thread usage
becomes a bottleneck with many accounts, only `data/providers/imap/`
changes.

**Three auth modes:** password, app password, and SASL XOAUTH2
with a token refresher. XOAUTH2 matters beyond Google and Microsoft: it
is the only non-password way into Yahoo and AOL, once a provider grants
it. Password and app password work. XOAUTH2 waits for the refresher: the
IMAP and SMTP modules speak it, but an account with `auth: xoauth2`
answers `501` until the service can renew its token. Server extensions
used where offered: `IDLE` (push), `CONDSTORE` (flags another client
changed), `UIDPLUS` and `MOVE`. `QRESYNC` is not used.

Gmail and Microsoft accounts *could* run over IMAP too, but their native
APIs give stable ids, threads, labels, delta and push, and need the same
OAuth consent anyway. IMAP stays the fallback for everything else.

### 5.2 POP3: yes, but reduced

POP3 knows one mailbox, no flags, no folders, no search and no push. The
`pop3` adapter therefore offers: one folder with the inbox role, list and
get via `UIDL`, attachment download, delete. Read state and search are not
supported (`501`), sending goes through SMTP. Recommendation: only offer
POP3 where a provider has no IMAP at all, which is rare today.

**Decided 2026-10-06, built:**

- **Read state and stars** are not supported. Setting them, or keywords,
  answers `501`. A message of a POP3 account is never unread or starred.
- **Deleting** is for good only, with `DELE`. A delete into the trash
  answers `501`: POP3 has no trash.
- **Search, folders and drafts** answer `501`. The one folder is the inbox.
- **The sync polls** the list of unique ids at the sync interval and
  compares it, as for IMAP without IDLE. The change feed, `whats_new` and
  webhooks report what arrived and what left. Its ids are not stable
  ids of a message, so the domain keeps the id mapping and the sync runs.
  The ids never move, so the mapping stays as it was.
- **Discovery** offers POP3 only where it finds no IMAP. A POP3 account
  can always be set up by hand, in the UI with the protocol to choose.
- **A server without `UIDL`** is refused when the account connects:
  without it no message keeps an id.

How the adapter works: a POP3 session sees the mailbox as at its login,
and the server locks the mailbox while it lasts. So every step logs in,
works and quits at once, and deletions take effect at `QUIT`. A list reads
the headers of its page with `TOP`, or the whole message where the server
has no `TOP`. A line longer than poplib's 2048 bytes is read: mail breaks
that limit of RFC 5322 often enough.

### 5.3 What each provider offers

Checked against provider documentation on 2026-09-24. **(unverified)**
marks what could not be confirmed on an official page.

| Provider | Native mail API | Credential for us | IMAP / SMTP | Adapter | Notes |
|---|---|---|---|---|---|
| Gmail, Google Workspace | Gmail API (REST): messages, threads, labels, drafts, send, `history.list` delta, push via Pub/Sub | OAuth 2.0, restricted scopes (5.5). App password still works for consumer accounts with 2-step verification | yes, XOAUTH2 or app password | `gmail` | password IMAP ("less secure apps") is gone for Workspace since 2025 |
| Microsoft 365, Outlook.com | Microsoft Graph (REST): messages, folders, send, search, per-folder delta, webhooks, immutable ids | OAuth 2.0 (Entra app registration) | XOAUTH2 only | `microsoft` | basic auth gone, EWS ending (5.4) |
| Fastmail | **JMAP**: everything incl. `/changes` delta and push | API token, created by the user, read-only or full | yes, app password | `jmap` | paid service |
| Stalwart, Cyrus (self-hosted) | **JMAP** | server-dependent | yes | `jmap` | Stalwart doubles as a JMAP test server |
| Zoho Mail | REST Mail API: messages, folders, labels, threads, search, send. No delta or push found **(unverified)** | OAuth 2.0 per data centre | yes, app password | `imap` | own adapter only on demand |
| Yahoo, AOL | none public | **app password**. OAuth for IMAP only after Yahoo approves the app and a commercial access agreement is signed | yes | `imap` | OAuth is not realistic for a self-hosted tool |
| iCloud Mail | none | app-specific password, 2FA required | IMAP / SMTP, no POP | `imap` | username often the local part only |
| GMX, web.de | none public | password, or application-specific password (required with 2FA) | yes, **must be switched on** in the web mailer | `imap` | may block logins behind a CAPTCHA or security filter |
| T-Online | none | the separate "password for email programs", not the Telekom login | yes | `imap` | |
| IONOS, Strato, freenet | none for mail content (IONOS's API manages domains, not mail) | mailbox password | yes (freenet: switch on first) | `imap` | |
| Posteo, mailbox.org | none | password, app passwords with 2FA (mailbox.org) | yes | `imap` | |
| Infomaniak | REST API for mail hosting administration, not message content **(unverified)** | app password | yes | `imap` | |
| Proton Mail | none | Bridge password | only through **Proton Mail Bridge**, local IMAP / SMTP, paid plans only | `imap` against the Bridge | the Bridge must run beside the service |
| Tuta | none | — | **none**, end-to-end encryption by design | **not supportable** | |
| Yandex | none for content | app password or OAuth token, both to be allowed in the settings | yes | `imap` | |

The picture is clear: **only Google, Microsoft and JMAP servers offer a
mail API worth an adapter.** Everyone else is IMAP, and for everyone else
an app password is the credential to ask for.

### 5.4 Microsoft: Graph only, and the deadlines

- **Graph is the adapter**, IMAP over XOAUTH2 at most a fallback. Graph
  brings delta per folder, change notifications and immutable ids that
  survive moves and work with delta and notifications.
- **EWS is not an option.** Exchange Online blocks it from **2026-10-01**
  unless a tenant has set up an allow list, and removes it for good on
  **2027-04-01**.
- **SMTP AUTH with basic auth** is switched off by default for existing
  tenants at the **end of December 2026**, the final removal date follows
  in the second half of 2027. Sending therefore goes through Graph, not
  SMTP.
- Outlook.com has accepted no basic auth since 2024-09-16.
- Rules of the implementation (phase 5): every call asks for immutable ids
  (`Prefer: IdType="ImmutableId"`), so the domain keeps no id mapping.
  Sending and drafts go as MIME, composed as for every provider.
  A draft is created from MIME and replaced by a new one, since Graph
  cannot change a draft's MIME. A mail is sent as such a draft: its copy
  in Sent Items keeps the draft's immutable id, which the send answers,
  the way Microsoft documents. A message is read from its MIME as well,
  so its bodies, `in_reply_to` and attachments, inline images among
  them, are those the other providers answer. Graph's own body is HTML
  for a plain text mail, and Graph lists no attachments for a mail with
  inline images only. Graph takes at most 4 MB per request, and the
  MIME travels in base64: a mail above 2.5 MiB is created without its
  files, which follow one by one, a file of 3 MB or more through an
  upload session in ranges, the ways Microsoft documents.
  Bcc recipients travel in a Bcc header **(unverified: that Exchange takes
  it out before delivery)**. Keywords are categories. `$answered` and
  `$forwarded` are the verb Outlook last carried out on a message
  (`PidTagLastVerbExecuted`), read and written as an extended property
  with the icon Outlook shows for it: one of the two at a time, as
  Outlook shows it. A change Exchange refuses as a conflict, as a mark
  set right after another one (seen live), is tried again after a pause.
  The other system keywords have no place: setting or taking one off
  answers `501`. A next-page
  cursor is a Graph path below `/me/` and never leaves the Graph host.
  No push yet.
- Exchange has no folder with the role `all`. The adapter shows one,
  "All Mail" with the id `all`: every folder but the trash and junk,
  which leave a page after Graph answers it, so a page can come back
  short. A message cannot be moved into it.
- Seen live with a personal account: `$search` ignores the preference for
  immutable ids, a message fetched by such an id comes back under it
  again, and `translateExchangeIds` is refused. A list filtered by
  `internetMessageId` answers with immutable ids, so the adapter looks
  search results up that way, in their own folder, twenty to a JSON
  batch. Outlook.com took several minutes to deliver a sent mail.
- The app asks for delegated `Mail.ReadWrite`, `Mail.Send`,
  `offline_access`, and `User.Read` for the address that signed in.
- **Decided 2026-09-27:** the address of an account comes from Graph
  `/me` (`mail`, else `userPrincipalName`), not from the ID token. Its
  `email` claim is not verified: anyone who manages a work or school
  tenant may set it. `User.Read` is asked for at the sign-in only. A
  refresh asks for the adapter's scopes alone, so refresh tokens granted
  before keep working.
- **Decided 2026-09-25:** the tenant is `common` by default, so personal
  and work or school accounts can sign in. `consumers`, `organizations` or
  one tenant narrow it. The app must then be registered for all Microsoft
  account users. A work tenant may require its administrator's consent
  before its users can sign in. The provider sends the browser back to
  `/ui/oauth/{provider}/callback`, a UI page.
- **Decided 2026-09-25:** a client id of the project, shipped with the
  service, as the default, so that people can connect Microsoft accounts
  without registering an app of their own. It is a public client
  (registered for mobile and desktop applications): no secret, PKCE
  alone, since a secret shipped with the software would not be secret.
  Such a client can only be sent back to `localhost`. A service on a
  server signs in with the device code flow instead (RFC 8628, a code
  entered at Microsoft's device login page). An app of the deployment's
  own, with a secret, stays the option for organisations that want or
  need one. Work tenants often admit apps of unverified publishers only
  with their administrator's consent. Publisher verification needs
  membership in Microsoft's partner programme.
- **Decided 2026-10-06:** one app per deployment. A client id in the
  settings names the deployment's own app, without one the project's app
  is used. Refresh tokens belong to the app that issued them, so after a
  change every Microsoft account signs in again. The UI offers both ways
  to sign in, in the browser and with a code, and the person chooses.
  The API offers the sign-in with a code: `POST
  /v1/oauth/{provider}/device`, then polling
  `POST /v1/oauth/{provider}/device/{sign_in_id}`. The sign-in in the
  browser is the UI's alone, since the provider sends the browser back
  to a page of the UI (decided 2026-10-07, after a review of the API:
  an API caller could start it but never finish it). A sign-in with a
  code is bound to the user who started it, like the one in the
  browser, and the provider is asked no more often than it allows.
- **Decided 2026-10-07:** where the project's app cannot send the browser
  back, because the service is not at localhost, the UI offers the
  sign-in with a code only.
- **Decided 2026-10-06:** `MAILBOX_SERVICE_PROVIDERS` names the kinds of
  account a deployment offers, a JSON list, every kind without it. The
  UI and the API offer only those: discovery leaves out the others, and
  connecting one is refused. Accounts connected before keep working and
  may sign in again.
- Planned, with push: change-notification subscriptions expire after a
  few days and are renewed by the worker **(unverified: exact
  lifetime)**. Today the worker asks delta queries.

### 5.5 Google: the verification question

The Gmail scope this service asks for, `https://mail.google.com/`, is a
**restricted scope**. A publicly distributed app using it
needs Google's verification plus a yearly security assessment (CASA). That
is out of reach for a self-hosted open-source project, and it does not have
to be reached:

- **Each deployment brings its own OAuth client**, created by the operator in
  their own Google Cloud project. Google exempts personal use (the operator
  and a few people known to them, under 100 users) and Workspace apps set
  to **Internal**. GOOGLE.md walks the operator through it.
- **The publishing status must be "In production", not "Testing".** An
  external app in testing gets refresh tokens that expire after **7 days**,
  and every Gmail account would drop to `needs_reauth` once a week. In
  production an unverified app shows a warning on consent, which the
  operator accepts for their own app.
- Gmail refresh tokens are revoked when the account password changes. The
  account then goes to `needs_reauth` (7.4).
- Push: `users.watch` publishes to Cloud Pub/Sub and has to be renewed at
  least every 7 days. Without Pub/Sub, the worker polls `history.list`,
  which is cheap. **The worker polls.** Pub/Sub is not built, since it
  needs another piece of Google Cloud set up (IDEAS.md).
- Quota: 250 units per user per second. Irrelevant for one person's
  mailbox, relevant for a bulk import.

The same consent screen covers the Gmail API and IMAP with XOAUTH2, so the
API costs nothing extra in verification. That settles `gmail` over `imap`
for Google accounts.

**Built 2026-10-09** (`data/providers/gmail/`, docs/GOOGLE.md), checked
live against a Gmail account (`live/gmail.py`):

- The client goes into the settings, `MAILBOX_SERVICE_OAUTH_GOOGLE_CLIENT_ID`
  with its secret, like an own Microsoft app. Without it, Gmail is not
  offered as a kind of account to sign in with, and the preset connects
  Gmail over IMAP with an app password.
- The scope is `https://mail.google.com/`, the only one that deletes for
  good. `gmail.modify` covers all but that.
- Google offers no sign-in with a code (RFC 8628) for Gmail scopes. The
  browser is the only way, sent back to the redirect URI of the client.
  The sign-in asks `access_type=offline` and `prompt=consent`, so every
  sign-in hands out a refresh token.
- Labels are folders (`LABELS`): the system labels with a role, and the
  labels a person made, nested by their names (`a/b` in `a`). "All Mail"
  is the folder `ALL_MAIL` with the role `all`. A message in the trash or
  the spam is in that folder alone. `STARRED` and `UNREAD` are flags.
  `IMPORTANT`, the categories and the chats are left out. Gmail has no
  keywords and lacks `keywords`: setting one answers 501. A draft reads `$draft`, from its
  label `DRAFT`, as on the other providers.
- A reply and its draft name the thread of the mail they answer, found
  by its `Message-ID` (`rfc822msgid:`). Gmail threads a reply only when
  told the thread, besides `In-Reply-To`, `References` and the subject.
- Changes come from `history.list` since a history id, polled by the
  worker (`Deltas`). Push through Pub/Sub is not built (IDEAS.md).

### 5.6 JMAP as a second generic protocol

JMAP (RFC 8620 / 8621) is what IMAP would look like if designed today:
JSON over HTTPS, stable ids, threads, `/changes` delta, push and sending
built in.

- Covers Fastmail today, and every Stalwart or Cyrus server, including a
  company's own.
- Fastmail API tokens are the simplest credential of all: created by the
  user, scoped read-only or full, no OAuth round trip.
- Implemented directly over httpx. It is a small JSON protocol, and a
  wrapper library would be one more dependency with its own licence to
  check.
- Stalwart runs in a container as the test mail server, and
  `live/jmap.py` checks the adapter against it (10).

**Decided 2026-10-06, built:**

- **The credential** is a password or an API token, chosen when the
  account is added. A password goes as HTTP Basic (Stalwart, Cyrus), a
  token as Bearer (Fastmail). Both are stored encrypted like any other.
- **Sending** goes through JMAP itself (RFC 8621 7), without SMTP
  settings. The message is stored in the drafts folder, submitted, and
  moved to the sent folder once the server took it.
- **The sync** asks what changed since a state (`Email/changes`), with the
  ids of the server, which stay when a message moves. The server's event
  source reports a change at once, as IDLE does for IMAP.
- **Discovery** asks `/.well-known/jmap` of the address's domain and the
  SRV record `_jmap._tcp`. Where a server offers JMAP and IMAP, JMAP comes
  first and IMAP stays a choice beside it.

How the adapter works: the session names the URLs of the API, of blobs and
of the event source. Each is used on the server the account names, by its
path, never by its host: the credential goes to no other host, and a
server that names itself otherwise behind a proxy still works. A message
can be in several folders (`labels`). JMAP reports changes for the whole
account, not per folder: a message counts as changed in the folder it is
in now and as removed from the others, so a move shows as one. A deleted
message reaches the change feed without a folder, since JMAP does not say
where it was. A message keeps its content as stored, so a draft that is
replaced gets a new id. Discovery asks the server once, without a
credential: a `401` names the schemes it takes, and only `Bearer` asks for
an API token. POP3 is offered only where neither IMAP nor JMAP is.

### 5.7 Dates to watch

| Date | What | Consequence here |
|---|---|---|
| passed, 2024-09-16 | Outlook.com: basic auth off | Microsoft only via OAuth |
| passed, 2025 | Google Workspace: password IMAP off | Google only via OAuth or app password |
| **2026-10-01** | Exchange Online: EWS blocked by default | never build on EWS |
| **end of 2026-12** | Exchange Online: SMTP AUTH basic auth off by default | send through Graph |
| **2027-04-01** | Exchange Online: EWS removed | — |
| recurring, 7 days | Gmail `users.watch` expires | not used: the worker polls `history.list` (5.5), Pub/Sub is an idea |
| recurring, days | Graph subscriptions expire (planned, with push) | the worker renews them |
