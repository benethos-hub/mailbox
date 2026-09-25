# Concept — Mailbox Service

> **Status: draft, 2026-09-24. The software is pre-alpha, version 0.1.0.**
> Describes the target design. What is built today is marked in
> [ROADMAP.md](ROADMAP.md). Facts about third-party products were taken
> from their public documentation on 2026-09-24. Items marked
> **(to verify)** could not be confirmed there.

## 1. Purpose

One REST API in front of many mail accounts at many providers. A client
talks to `/v1/accounts/{account_id}/...` and never learns whether the account
is Gmail, Microsoft 365, GMX over IMAP or a POP3 mailbox. On top of the API
sits an MCP server, so an assistant can read, search, triage and send mail
across all connected accounts.

Two layers, strictly separated:

```
 MCP client (Claude, ...)
        │  MCP (stdio / streamable HTTP)
 ┌──────▼───────────┐
 │  MCP server      │  thin: tools → REST calls, compact output
 └──────┬───────────┘
        │  HTTPS + bearer token        ◄── the OpenAPI document is the contract
 ┌──────▼───────────┐
 │  REST API        │  FastAPI, /v1, OpenAPI 3.1
 │  account store   │  SQLite, credentials encrypted
 │  adapters        │  imap · pop3 · gmail · microsoft
 └──────┬───────────┘
        │  IMAP/SMTP · POP3 · Gmail API · Microsoft Graph
    mail providers
```

The MCP server never imports an adapter. Everything it can do, any other
REST client can do too.

### 1.1 Inside the service

**Decided 2026-09-24:** three layers, imports only point down.

```
 web/          PRESENTATION ─ HTTP only
   routes/       JSON API under /v1  ◄── scripts, apps, the MCP server
   pages/        configuration UI    ◄── a person in the browser
      │  who is calling (token or session) → the domain
 domain/       BUSINESS LOGIC ─ no HTTP
   accounts, mailbox, rights, id mapping, sync
      │
 data/         DATA ─ decides nothing
   models/     provider-neutral types, one module per subject
   providers/  imap · gmail · microsoft · pop3 · memory, behind a registry
   storage/    own records: accounts, users, credentials
   secrets/    envelope encryption, key providers, backup
   discovery/  autodiscovery sources
```

- **Two front ends, one domain.** The JSON API and the configuration UI are
  both part of the web layer and both call the same domain services. The UI
  is not a client of the API over HTTP. It runs in the same process and
  skips the network hop, but it goes through the same domain, and so through
  the same checks.
- **Rights are enforced in the domain.** The web layer only establishes who
  is calling: a bearer token on the API, a session after password or passkey
  login in the UI (7.5). What that user may do is decided once, in the
  domain, for both front ends.
- **The configuration UI** covers what a person has to do by hand:
  connecting accounts and entering app passwords, the OAuth round trip for
  Gmail and Microsoft, users, roles and tokens, the recovery key, and a
  status view of accounts and sync. Server-rendered pages, not in the
  OpenAPI document, under `/ui`. Forms carry CSRF protection, since a
  session cookie authenticates them.

  **Decided 2026-09-24:** the UI comes before the new providers and covers
  everything the REST API does. A person signs in with an API token of its
  user (or the admin key). Password with TOTP can follow as a credential
  kind of its own. Its texts are English. Built with Jinja2 templates,
  htmx and one stylesheet, without a build step.

  Rules of the implementation: the session lives on the server, the cookie
  (`HttpOnly`, `SameSite=Strict`, path `/ui`) carries only a random id, and
  every request authenticates the token anew, so revoking it ends the
  session. Sessions end after 8 hours without a request and with a
  restart. A content security policy allows no inline script or style and
  no framing. A form answers with a redirect (Post/Redirect/Get).
  Guessing is slowed down: a client address that fails to sign in ten
  times within fifteen minutes is locked out for fifteen minutes, on the
  UI and on the API alike, whatever the credential kind. Behind a proxy,
  `MAILBOX_SERVICE_FORWARDED_ALLOW_IPS` names the proxy so the client
  address comes from `X-Forwarded-For`.
- **No HTTP below the web layer**, no decisions in the data layer,
  providers reached only through their registry. A test checks the
  direction of every import.

## 2. Scope

**In scope:** connecting and managing accounts, folders, message list /
search / read, flags and moves, attachments, sending incl. reply and forward,
drafts, a change feed, webhooks, and the MCP server.

**Out of scope (for now):** calendar and contacts, hosting mail, spam
filtering, a full local mirror of mailboxes, multi-tenant SaaS operation.

## 3. Design principles of the API

The decisions that shape every endpoint.

- **The account is part of the path.** `/v1/accounts/{account_id}/…`, never
  a query parameter and never implied by the token. A request says which
  mailbox it is about, and rights are checked against exactly that.
- **Folders are an array on the message.** `folder_ids` covers Gmail labels,
  where a message sits in several places at once, and IMAP folders, where
  it sits in one, with the same model.
- **Message ids survive a move.** A client, and a model, keeps an id between
  calls. An id that changes when the message is filed breaks every
  follow-up call (4.1).
- **Sending is idempotent on request.** An `Idempotency-Key` header makes a
  retried send return the first result instead of sending twice. An agent
  retries tool calls, and a duplicate mail cannot be taken back.
- **Changes can be pulled.** `/changes?since=` answers "what changed since
  X" without a webhook, since an MCP server has no public URL to receive
  one. Webhooks exist in addition, not instead.
- **Reply and forward by reference.** The client names the message and the
  action. The server sets `In-Reply-To`, `References`, the subject prefix
  and the quote.
- **Bulk operations.** Filing or marking fifty messages is one call.
- **The raw source is available** for archiving and debugging.
- **Rights per user, per account, per operation** (7.5), with tokens as one
  kind of credential.
- **Cursor pagination everywhere**, with an opaque `next_cursor`.

## 4. Resource model

| Resource | Notes |
|---|---|
| **Account** | one mailbox at one provider. `id` is ours (`acc_…`). Carries `provider`, `email`, `status` (`connected`, `needs_reauth`, `disabled`), `capabilities`. |
| **Folder** | `id`, `name`, `role` (RFC 6154 special use: inbox, sent, drafts, trash, junk, archive, all), `parent_id`, counts, `subscribed` (IMAP, decided 2026-09-24). Gmail labels are folders. |
| **Message** | summary (list) and full form (get). `folder_ids` is an array. `unread`, `starred` as booleans, further flags as `keywords`. |
| **Thread** | where the provider supports it (Gmail, Graph conversations), otherwise built from `References` / `In-Reply-To`. |
| **Attachment** | metadata on the message, content via its own download route. |
| **Draft** | a message with the draft role, own routes because providers treat it specially. |
| **Change** | an entry in the change feed: `{type, id, account_id, at}`. |
| **Webhook** | callback URL + event list + signing secret. |
| **Token** | an API token with scopes. |

### 4.1 Message ids

Our id must be stable across moves, because a client (and a model) keeps it
between calls. Per adapter:

| Adapter | Source of stability |
|---|---|
| Gmail | Gmail message id, stable by design |
| Microsoft | Graph with `Prefer: IdType="ImmutableId"` |
| JMAP | the JMAP email id, immutable by the standard |
| IMAP | `OBJECTID` (RFC 8474) or Gmail's `X-GM-MSGID` where offered, otherwise our own id mapped to `(folder, UIDVALIDITY, UID)` in the store, updated when *we* move a message and re-resolved by `Message-ID` header when the mapping breaks |
| POP3 | `UIDL` |

Ids are opaque strings to clients. Nothing may parse them.

#### IMAP without `OBJECTID`

**Decided 2026-09-24:**

- **An id mapping in the store.** Our id (`msg_…`) points to a folder,
  `UIDVALIDITY` and UID. Per message the store keeps only the account, the
  folder, `UIDVALIDITY`, the UID, the `Message-ID` header and our id, plus
  a state per folder. No subject, no sender, no content. Decided later the
  same day: also `In-Reply-To` and `References`, for threads (6.3).
- **Our own moves** update the mapping from the new UID the server reports
  with `COPYUID` (UIDPLUS).
- **Moves by others** (another client, a server rule) are found by the sync
  worker (8.1): a message that leaves one folder and one with the same
  `Message-ID` that arrives in another is the same message, and keeps its
  id. A `UIDVALIDITY` change is handled the same way.
- **A lookup that finds the message gone** from its place syncs the
  account once and tries again. Only the message itself counts: a
  missing attachment, draft or folder is not a moved message.
- **Ambiguous matches are never guessed.** Several candidates with the same
  `Message-ID`, or none, and the old id answers `404`.

## 5. Provider adapters and libraries

Every adapter implements `data.providers.base.MailProvider` and declares a
set of `Capability` values. The API answers `501 not_supported` for what an
adapter cannot do, and `GET /v1/accounts/{id}` lists the capabilities so a
client can tell in advance.

| Adapter | Covers | Library | Licence | Notes |
|---|---|---|---|---|
| `imap` | everything without a better API: GMX, web.de, T-Online, Yahoo, AOL, iCloud, Posteo, mailbox.org, IONOS, Strato, Zoho, own servers, Proton via Bridge | **IMAPClient** (protocol), the mail parser of **imap-tools** (messages) | BSD-3-Clause, Apache-2.0 | synchronous, run in a worker thread. Auth: password, app password **and XOAUTH2** |
| `smtp` | sending for `imap`, `jmap`-less and `pop3` accounts | stdlib **smtplib**, for now (decided 2026-09-24) | PSF | synchronous, run in a worker thread like IMAP, also XOAUTH2 |
| `microsoft` | Microsoft 365, Outlook.com | Microsoft Graph over **httpx** | — | OAuth 2.0, the only sensible route (5.4) |
| `gmail` | Gmail, Google Workspace | Gmail REST API over **httpx** | — | OAuth 2.0, no Google SDK needed (5.5) |
| `jmap` | Fastmail, Stalwart, Cyrus, any JMAP server | JMAP (RFC 8620/8621) over **httpx** | — | API token or OAuth. A second generic protocol next to IMAP (5.6) |
| `pop3` | legacy mailboxes | stdlib **poplib** | PSF | synchronous, worker thread, reduced (5.2) |
| `memory` | tests and development | — | — | built |

### 5.1 IMAP: IMAPClient for the protocol, imap-tools for parsing

**Decided 2026-09-24:** the protocol goes through **IMAPClient**, in
`providers/protocols/imap.py`. It parses every server answer and returns
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

**Three auth modes from the start:** password, app password, and SASL
XOAUTH2 with a token refresher. XOAUTH2 matters beyond Google and Microsoft:
it is the only non-password way into Yahoo and AOL, once a provider grants
it. Server extensions used where offered: `IDLE` (push), `CONDSTORE` /
`QRESYNC` (cheap delta), `UIDPLUS` and `MOVE`, `OBJECTID` (stable ids, 4.1).

Gmail and Microsoft accounts *could* run over IMAP too, but their native
APIs give stable ids, threads, labels, delta and push, and need the same
OAuth consent anyway. IMAP stays the fallback for everything else.

### 5.2 POP3: yes, but reduced

POP3 knows one mailbox, no flags, no folders, no search and no push. The
`pop3` adapter therefore offers: one folder with the inbox role, list and
get via `UIDL`, attachment download, delete. Read state and search are not
supported (`501`), sending goes through SMTP. Recommendation: only offer
POP3 where a provider has no IMAP at all, which is rare today.

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
  in the second half of 2027. Sending therefore goes through Graph
  `sendMail`, not SMTP.
- Outlook.com has accepted no basic auth since 2024-09-16.
- Rules of the implementation (phase 5): every call asks for immutable ids
  (`Prefer: IdType="ImmutableId"`), so the domain keeps no id mapping.
  Sending and drafts go as MIME, composed as for every provider.
  `sendMail` keeps the copy in Sent Items itself. A draft is created from
  MIME and replaced by a new one, since Graph cannot change a draft's MIME.
  Bcc recipients travel in a Bcc header **(unverified: that Exchange takes
  it out before delivery)**. Keywords are categories. `$answered` and the
  other system keywords have no place and are not stored. A next-page
  cursor is a Graph path below `/me/` and never leaves the Graph host.
  No push yet.
- Seen live with a personal account: `$search` ignores the preference for
  immutable ids, a message fetched by such an id comes back under it
  again, and `translateExchangeIds` is refused. A list filtered by
  `internetMessageId` answers with immutable ids, so the adapter looks
  search results up that way, in their own folder, twenty to a JSON
  batch. Outlook.com took several minutes to deliver a sent mail.
- Each deployment registers its own app in Entra ID (delegated
  `Mail.ReadWrite`, `Mail.Send`, `offline_access`, and `openid`, `email`,
  `profile` for the address that signed in).
- **Decided 2026-09-25:** the tenant is `common` by default, so personal
  and work or school accounts can sign in. `consumers`, `organizations` or
  one tenant narrow it. The app must then be registered for all Microsoft
  account users. A work tenant may require its administrator's consent
  before its users can sign in. The provider sends the browser back to
  `/ui/oauth/{provider}/callback`, a UI page.
- **Planned (decided 2026-09-25):** a client id of the project, shipped
  with the service, as the default, so that people can connect Microsoft
  accounts without registering an app of their own. It is a public client
  (registered for mobile and desktop applications): no secret, PKCE
  alone, since a secret shipped with the software would not be secret.
  Such a client can only be sent back to `localhost`. A service on a
  server signs in with the device code flow instead (a code entered at
  Microsoft's device login page). An app of the deployment's own, with a
  secret as today, stays the option for organisations that want or need
  one. Work tenants often admit apps of unverified publishers only with
  their administrator's consent. Publisher verification needs membership
  in Microsoft's partner programme.
- Change-notification subscriptions expire after a few days and are
  renewed by the worker **(unverified: exact lifetime)**.

### 5.5 Google: the verification question

The Gmail scopes this service needs (`gmail.modify`, or `mail.google.com`
for IMAP) are **restricted scopes**. A publicly distributed app using them
needs Google's verification plus a yearly security assessment (CASA). That
is out of reach for a self-hosted open-source project, and it does not have
to be reached:

- **Each deployment brings its own OAuth client**, created by the operator in
  their own Google Cloud project. Google exempts personal use (the operator
  and a few people known to them, under 100 users) and Workspace apps set
  to **Internal**. The configuration UI walks the operator through it.
- **The publishing status must be "In production", not "Testing".** An
  external app in testing gets refresh tokens that expire after **7 days**,
  and every Gmail account would drop to `needs_reauth` once a week. In
  production an unverified app shows a warning on consent, which the
  operator accepts for their own app.
- Gmail refresh tokens are revoked when the account password changes. The
  account then goes to `needs_reauth` (7.4).
- Push: `users.watch` publishes to Cloud Pub/Sub and has to be renewed at
  least every 7 days. Without Pub/Sub, the worker polls `history.list`,
  which is cheap. **Polling is the default**, Pub/Sub an option, since it
  needs another piece of Google Cloud set up.
- Quota: 250 units per user per second. Irrelevant for one person's
  mailbox, relevant for a bulk import.

The same consent screen covers the Gmail API and IMAP with XOAUTH2, so the
API costs nothing extra in verification. That settles `gmail` over `imap`
for Google accounts.

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
- Stalwart runs in a container and serves as the JMAP (and IMAP) server
  for integration tests (10).

### 5.7 Dates to watch

| Date | What | Consequence here |
|---|---|---|
| passed, 2024-09-16 | Outlook.com: basic auth off | Microsoft only via OAuth |
| passed, 2025 | Google Workspace: password IMAP off | Google only via OAuth or app password |
| **2026-10-01** | Exchange Online: EWS blocked by default | never build on EWS |
| **end of 2026-12** | Exchange Online: SMTP AUTH basic auth off by default | send through Graph |
| **2027-04-01** | Exchange Online: EWS removed | — |
| recurring, 7 days | Gmail `users.watch` expires | the worker renews it |
| recurring, days | Graph subscriptions expire | the worker renews them |

### 5.8 Autodiscovery

**Requirement, 2026-09-24:** adding an account starts with the email
address, nothing else. The service works out provider, adapter, servers,
ports, encryption and the kind of credential to ask for. Only what cannot
be discovered is asked for.

```
 user@example.de
      │
      ▼
 discovery  ──►  candidates, ranked, each with its source
      │           "GMX via IMAP, needs an app password, IMAP must be enabled"
      ▼
 person confirms  ──►  credential entered  ──►  verify  ──►  account stored
```

#### Everything stays in the service

Discovery and every connection run in the self-hosted service. No account
and no credential is handed to a third-party cloud to sync from there.
Nothing leaves the service except the lookups listed below, and each lookup
that tells a third party which domain is being set up can be switched off.

#### Sources, in order

Each source is asked in turn. The first confident answer wins, the others
still run in parallel with a short timeout, so a slow source does not hold
up the result.

| # | Source | What it asks | Covers |
|---|---|---|---|
| 1 | **Own presets** | domain in the built-in list (5.3 as data: servers, credential kind, hints) | the providers we know, with hints no other source has ("switch on IMAP first", "use the email password, not the login") |
| 2 | **ISP autoconfig** | `https://autoconfig.{domain}/mail/config-v1.1.xml?emailaddress=…`, then `https://{domain}/.well-known/autoconfig/mail/config-v1.1.xml` | providers and self-hosters who publish an autoconfig file |
| 3 | **JMAP well-known** | `https://{domain}/.well-known/jmap`, SRV `_jmap._tcp.{domain}` | JMAP servers (5.6) |
| 4 | **ISPDB** | `https://autoconfig.thunderbird.net/v1.1/{domain}`, Thunderbird's shared database | many smaller providers. Tells Mozilla the domain, so it can be switched off |
| 5 | **MX lookup** | MX record of the domain, then sources 1 and 4 for the MX host's base domain | custom domains hosted elsewhere: MX at `google.com` means Google Workspace, at `protection.outlook.com` Microsoft 365, at `mx.ionos.de` IONOS |
| 6 | **Microsoft realm** | Microsoft's user-realm and Autodiscover v2 endpoints for the address | recognises a Microsoft 365 tenant behind any domain **(to verify: exact endpoints and their stability)** |
| 7 | **SRV records** | RFC 6186: `_imaps._tcp`, `_imap._tcp`, `_submission._tcp`, `_submissions._tcp` | mail servers that publish SRV |
| 8 | **Guessing** | `imap.{domain}`, `mail.{domain}`, `smtp.{domain}` on 993/143 and 465/587 | last resort, lowest confidence |

For every IMAP or SMTP candidate the service then reads the server's
`CAPABILITY`: which auth mechanisms it offers (`AUTH=XOAUTH2`,
`AUTH=PLAIN`) decides whether to ask for OAuth or a password, and `IDLE`,
`CONDSTORE`, `MOVE` feed the account's capabilities.

The result tells the person what to do, not just where the server is:

- **Google or Microsoft:** "Sign in with Google", "Sign in with Microsoft".
  The OAuth round trip, no password.
- **Fastmail:** "Create an API token under Settings, Privacy & Security".
- **GMX, web.de, freenet:** "Switch on IMAP in the web mailer first", link
  to the provider's help page.
- **Yahoo, iCloud, AOL:** "Create an app password", link.
- **Tuta:** "Tuta offers no access for other programs", nothing to connect.
- **Proton:** "Requires Proton Mail Bridge on this machine, paid plans only".

#### Security rules

Autodiscovery decides where a password is sent. That makes it an attack
surface, and a known one: clients that, failing on the real domain, fell
back to `autodiscover.{tld}` have sent credentials at scale to whoever had
registered that domain.

1. **Discovery never sends a credential.** It only looks up and connects
   anonymously (`CAPABILITY`, TLS handshake). The password is entered after
   the result is shown, and goes only to the server the person confirmed.
2. **No fallback outside the domain.** Never `autodiscover.{tld}`, never a
   parent domain that is a public suffix. The Public Suffix List decides
   where a domain ends.
3. **HTTPS only**, with certificate verification, for every autoconfig and
   JMAP lookup. The autoconfig format still allows plain HTTP, this service
   does not.
4. **Trust follows the source.** Presets and results over HTTPS from the
   address's own domain count as confirmed. A server that SRV records, MX
   or guessing point to on a **different** domain is shown as unconfirmed
   and needs an explicit yes. DNS without DNSSEC can be forged.
5. **TLS is required.** Candidates without TLS or STARTTLS are dropped, and
   a STARTTLS offer is followed, never skipped.
6. **No requests into the local network.** Discovery makes the service
   connect to addresses derived from user input, which is how server-side
   request forgery works. Hosts resolving to private, loopback or
   link-local addresses are refused, unless an operator allows a list of
   internal mail servers in the settings. The same check runs on the
   hosts in an account's settings (`host`, `smtp_host`) when the account
   is created or changed, before the first connection: `400`.
7. **Safe XML.** Autoconfig files are parsed with `defusedxml`, never the
   plain standard-library parser, so a hostile file cannot expand entities
   or read local files.
8. **Limits.** Short timeouts, a cap on redirects and response size, a rate
   limit per user, and results cached per domain for a day.
9. **Privacy switches.** ISPDB and the Microsoft lookup each tell a third
   party which domain is being set up, and each can be switched off. The
   other sources only talk to the domain itself.

#### In the API

| Method | Path | Right | Purpose |
|---|---|---|---|
| POST | `/v1/discovery` | `accounts.manage` | body `{"email": "…"}`, returns ranked candidates |

POST rather than GET, so the address does not end up in access logs. A
candidate carries: adapter, servers with host, port and encryption, the
credential kind to ask for, OAuth provider if any, hints with help links,
`source`, `confirmed` (4 above), and the capabilities read from the server.
`POST /v1/accounts` then takes the chosen candidate plus the credential, and
verifies before it stores (7.4). The configuration UI is the main user:
address field, result, then either an OAuth button or a password field.

#### In the code

Each source is a module under `data/discovery/`, behind one
`DiscoverySource` protocol, so a source can be added, removed or switched off
without touching the others. `domain/discovery.py` runs them, applies the
security rules, ranks and merges. The presets are data, one file, shared
with the provider hints of 5.3. New dependencies, each wrapped in one
module: `dnspython` for MX and SRV (the standard library cannot query them),
`defusedxml` for the XML, `publicsuffixlist` for where a domain ends.

**Decided 2026-09-24:** the Public Suffix List is the copy bundled with
`publicsuffixlist`, updated with the package, no download at runtime. It is
wrapped in one module so a live list can be added later.

### 5.9 Being a good client

Providers protect themselves against clients that log in too often or ask
too much. GMX, web.de and T-Online answer with a CAPTCHA or a temporary
lock, and a locked account also locks out its owner's other mail programs.
The service therefore behaves conservatively towards every provider:

- **One rate limiter per account.** Every request to a provider passes it,
  retries and paging follow-ups included. The limits come from the preset of
  the provider (5.8), with a cautious default for unknown servers.
- **Few connections.** One IMAP connection per account for commands, a
  second one only for `IDLE`. Never one per API request.
- **A failed login is not retried.** After one authentication failure the
  account goes to `needs_reauth`, the event `account.needs_reauth` is raised,
  and nothing tries that credential again until it is replaced or a person
  runs `verify`. Repeating a wrong password is exactly what triggers a lock.
  A connection the server drops during the login is not a failed login:
  it is retried like any other dropped connection.
- **Backoff on everything else.** Timeouts, connection errors, `429` and
  `503` are retried with exponential backoff and jitter, `Retry-After` is
  honoured (Graph's as a pause during which nothing is sent), and a
  persistently unreachable account is shown as `unreachable` rather than
  hammered. A retried step must not do its work twice: an IMAP `APPEND`
  is preceded by a search for the message's `Message-ID`, so a draft or a
  sent copy stored before the connection dropped is found, not stored
  again.
- **Push before polling.** `IDLE` where offered, renewed before the 29
  minutes of RFC 2177 run out. Polling intervals are per preset and
  conservative.
- **Say who we are.** The IMAP `ID` command (RFC 2971) sends name and
  version where the server supports it. Some providers require it.

### 5.10 Encodings and other traps

To be kept in mind from the first IMAP line on, and covered by tests:

- **Folder names** travel in modified UTF-7 (RFC 3501): "Entwürfe" arrives as
  `Entw&APw-rfe`. `UTF8=ACCEPT` (RFC 6855) is used where the server offers
  it. The API only ever shows the decoded name.
- **Special folders without `SPECIAL-USE`.** Many servers name them in the
  mailbox language: Gesendet, Entwürfe, Papierkorb, Spam, Archiv. A name
  list per language maps them to roles when the server announces none.
- **Headers** in RFC 2047 encoding, with wrong or missing charset
  declarations. Decoding falls back to a detected charset rather than
  failing the whole message.
- **Internationalised domains** (IDN): punycode on the wire and in DNS
  (autodiscovery), Unicode in the API.
- **Addresses with non-ASCII local parts** need SMTPUTF8 (RFC 6531). Sent
  only when the server announces it, otherwise refused with a clear error.
  Domains go in punycode on the envelope.
- **Bodies are composed 7bit clean**: text beyond ASCII is encoded, since
  the service asks no SMTP server for 8BITMIME.
- **Dates** in every format a `Date` header has ever carried. Stored and
  returned in UTC with offset.

## 6. REST API

Base path `/v1`, JSON, bearer authentication on everything except
`/health`. `{acc}` stands for `/v1/accounts/{account_id}`.

### 6.1 Accounts

| Method | Path | Purpose |
|---|---|---|
| GET | `/v1/accounts` | list |
| POST | `/v1/accounts` | create with credentials (IMAP/POP3/SMTP, app password), connection is tested first |
| GET | `/v1/accounts/{account_id}` | get, including `status` and `capabilities` |
| PATCH | `/v1/accounts/{account_id}` | display name, settings, new password |
| DELETE | `/v1/accounts/{account_id}` | remove, credentials deleted |
| POST | `/v1/accounts/{account_id}/verify` | test the connection now |
| POST | `/v1/oauth/{provider}/start` | start OAuth for Microsoft (later Gmail): the provider's sign-in URL, to connect an account or, with `account_id`, sign it in again |
| GET | `/ui/oauth/{provider}/callback` | where the provider sends the browser back: a UI page, not part of the API. The person is signed in to the UI as the user who started. The account is created or signed in again |
| POST | `/v1/discovery` | autodiscovery from the email address alone: adapter, servers, credential kind, hints (5.8) |
| GET | `/v1/providers` | the built-in presets, the same data discovery uses first |

### 6.2 Folders

| Method | Path | Purpose |
|---|---|---|
| GET | `{acc}/folders` | list |
| POST | `{acc}/folders` | create |
| PATCH | `{acc}/folders/{folder_id}` | rename, move |
| DELETE | `{acc}/folders/{folder_id}` | delete |

Rules of the implementation (phase 2):

- A new folder goes into the user's personal namespace (RFC 2342), e.g.
  below `INBOX.` where the server keeps every folder there. It is
  subscribed, since Outlook and other clients list only subscribed
  folders. Renaming moves the subscription along, deleting drops it.
- Folders with a role (inbox, sent, trash, ...) are neither renamed nor
  deleted: `409`. `RENAME INBOX` would move the inbox's messages.
- Only an empty folder without subfolders is deleted, otherwise `409`: on
  many servers `DELETE` takes the messages inside with it.
- On IMAP a folder's id follows its name and changes when it is renamed.
  The messages inside keep their ids: a sync follows them at once (4.1).

### 6.3 Messages

| Method | Path | Purpose |
|---|---|---|
| GET | `/v1/messages` | list and search **across accounts** (6.6) |
| GET | `{acc}/messages` | list and search in one account (6.6) |
| GET | `{acc}/messages/{id}` | full message, `?body=text\|html\|both\|none` |
| PATCH | `{acc}/messages/{id}` | `unread`, `starred`, `keywords`, `folder_ids` (a move is a change of `folder_ids`) |
| DELETE | `{acc}/messages/{id}` | to trash, `?permanent=true` expunges |
| GET | `{acc}/messages/{id}/raw` | RFC 822 source (`message/rfc822`) |
| GET | `{acc}/messages/{id}/attachments/{att_id}` | attachment content, streamed |
| POST | `{acc}/messages/batch` | bulk `update` / `move` / `delete` for up to 100 ids, per-id result |
| GET | `{acc}/threads` | thread list (capability `threads`) |
| GET | `{acc}/threads/{thread_id}` | thread with its message summaries |

**Decided 2026-09-24, changing messages:**

- `PATCH` answers the changed message as a summary, with the same id.
- Moving needs `MOVE` or `UIDPLUS` on an IMAP server. Without both, a move
  would have to expunge the whole folder, other clients' deleted messages
  included, so it answers `501 not_supported`.
- `DELETE` without a folder with the trash role answers `409`, instead of
  deleting for good.
- Permanent deletion is the right `delete_message_permanent` in the group
  `mail.delete`, so it can also be granted on its own.

A message already in the trash answers `DELETE` without `permanent` with
`409`: otherwise two calls with `mail.write` would delete for good what
needs `mail.delete`. Deleting for good needs `UIDPLUS` on an IMAP server,
for the same reason as a move. On Microsoft, Graph's delete of a message
outside Deleted Items only moves it there, so the adapter moves the
message into the trash and deletes it from there; a deleted or replaced
draft goes the same way.

`keywords` follow JMAP (RFC 8621): `$answered`, `$forwarded`, `$draft` and
the provider's own keywords as they are. `\Seen` and `\Flagged` are
`unread` and `starred`. A `PATCH` with `keywords` replaces the list.

**Decided 2026-09-24, threads for IMAP:** IMAP's `THREAD` extension
(RFC 5256) works within one folder only, while a conversation is spread
over the inbox, the sent folder and the archive. The service builds IMAP
threads itself, across all folders, from `Message-ID`, `In-Reply-To` and
`References` in the id mapping (4.1).

### 6.4 Sending and drafts

| Method | Path | Purpose |
|---|---|---|
| POST | `{acc}/send` | send. Body: recipients, subject, text / html, attachments, optional `reference: {message_id, action: reply\|reply_all\|forward}`. Header `Idempotency-Key` |
| GET | `{acc}/drafts` | list |
| POST | `{acc}/drafts` | create (same body as send) |
| PUT | `{acc}/drafts/{draft_id}` | replace, `keep_attachments` names stored attachments that stay |
| DELETE | `{acc}/drafts/{draft_id}` | delete |
| POST | `{acc}/drafts/{draft_id}/send` | send a draft, `Idempotency-Key` |
| GET | `{acc}/sends` | the audit of sends, newest first |

**Decided 2026-09-24, reply and forward:**

- After a reply the original gets the flag `\Answered`, after a forward the
  keyword `$Forwarded`, so other mail clients show it too.
- `reference.forward_as` chooses how a forward carries the original:
  `inline` (the default, as in common mail clients: quoted with its
  headers, its attachments attached) or `attachment` (the unchanged
  original as `message/rfc822`). Ignored for replies.

Rules of the implementation (phase 2): a reply without recipients goes to
the original's `Reply-To`, else its sender. `reply_all` adds everyone in
`To` and `Cc` except the account itself. Named recipients and a subject
win over these. A `reference` needs `get_message` besides `send_message`:
a reply quotes the original and a forward passes it on, so a user who may
only send cannot get at mail this way. When the flag on the original
cannot be set, the send still counts as done.

Rules of the implementation for drafts (phase 2):

- A draft lives where mail clients keep drafts: on IMAP in the folder with
  the drafts role, flagged `\Draft`. An account without one answers `409`.
- Its id is a message id, so `get_message` and the raw source read it. The
  draft routes reach only messages in the drafts folder: any other id
  answers `404`, so the right `drafts` cannot touch other mail.
- `PUT` replaces the whole draft. IMAP cannot change a stored message, so
  the new one is appended and the old one deleted. The id follows through
  the id mapping (4.1).
- A draft keeps its Bcc recipients, and its `reference` in the header
  `X-Mailbox-Service-Reference`, until it is sent. Both are removed before it
  goes out. The quote of a reply or forward is written when the draft is
  made, as a mail client does.
- `get_message` shows a draft's `reference`. Replaced with that reference
  and `quote: false`, the draft keeps its link to the original (In-Reply-To,
  References, the mark after sending) and nothing of the original is added
  again: the text holds the quote already. The reference of any message
  that is not a draft is not shown: in a received mail the header is the
  sender's.
- A deleted draft is gone for good, not moved to the trash.
- `send_draft` sends the draft as stored, with the date of the send, and
  then deletes it. The sent folder gets its read copy as with `send`. The
  reference a draft kept marks its original. A draft without recipients
  answers `400`. It needs only `send_draft`: the draft was written by
  whoever may write drafts.

Sending is **synchronous** in phase 2: `200` means the provider accepted the
message. After an SMTP send the copy is appended to the sent folder unless
the provider does that itself (Gmail, Graph). A queued outbox with `send_at`
is a later option (see IDEAS.md).

`Idempotency-Key`: the result of the first request is stored for 24 hours.
The same key with the same body returns the stored result, with a different
body `409 idempotency_conflict`. A key counts per account and per caller:
the same key from another user is a conflict, never the first caller's
result. Requests with the same key run one after the other, so a retry
that arrives while the first is still sending waits for its result. A
request that fails stores nothing and may be tried again.

### 6.5 Changes and webhooks

| Method | Path | Purpose |
|---|---|---|
| GET | `{acc}/changes?since=<state>` | created / updated / deleted message ids since a state token, plus a new state |
| GET | `/v1/changes?since=<state>` | the same across all accounts |
| GET / POST | `/v1/webhooks` | list, register (URL, events, account filter) |
| DELETE | `/v1/webhooks/{webhook_id}` | remove |

Events: `message.created`, `message.updated`, `message.deleted`,
`message.sent`, `account.needs_reauth`. Payloads carry ids only, signed with
HMAC-SHA256 in a header. The source is IMAP IDLE / polling, Gmail
`history.list` and Graph delta queries, all normalized into the change feed.

### 6.6 Listing, search and pagination

`GET {acc}/messages` parameters:

| Parameter | Meaning |
|---|---|
| `folder` | folder id, or a role such as `inbox`. Left out: every folder on a Microsoft account, the inbox on IMAP |
| `q` | free text (subject, addresses, body where the provider can) |
| `from`, `to`, `subject` | structured filters |
| `after`, `before` | date range, ISO 8601 |
| `unread`, `starred`, `has_attachments` | booleans |
| `native` | provider's own syntax, passed through (Gmail search, IMAP SEARCH), capability `native_search` |
| `limit` | 1–200, default 50 |
| `cursor` | opaque, from `next_cursor` of the previous page |

Every list answers `{"items": [...], "next_cursor": "..."}`. There is no
total count, because IMAP and Graph cannot provide one cheaply after a
filter.

Rules of the implementation (built before phase 3):

- Text filters are case-insensitive parts, as IMAP `SEARCH` compares them.
  They hold no control characters (`422`): IMAP clients quote search text
  but keep line breaks, which would end the command and start another.
- `after` and `before` are days, as IMAP searches by day: `after` includes
  its day, `before` does not.
- `has_attachments` on IMAP is a `multipart/mixed` message, the same rule
  as the field in a summary.
- `native` is not built yet.

#### Across accounts

`GET /v1/messages` (`list_all_messages`) searches several accounts in one
call. It is what "what came in today" and "find the mail from the tax
advisor" need, whichever account it went to.

- Same parameters as above, plus `accounts` (a list of ids). Without it,
  every account the user may read.
- **Rights filter, not fail.** Accounts without `mail.read` for this user are
  left out silently, like in `list_accounts`.
- `folder` takes a **role** only (`inbox`, `sent`, …), since folder ids
  belong to one account.
- The accounts are asked in parallel, the results merged by date, newest
  first. The cursor is opaque and carries the position in every account.
- **One slow or failing account does not fail the request.** The answer is
  marked incomplete and says which account failed and why:

  ```json
  {"items": [...], "next_cursor": "...",
   "incomplete": [{"account_id": "acc_x", "code": "provider_error"}]}
  ```
- Every item carries its `account_id`.

### 6.7 Errors

One envelope for every error the API raises itself:

```json
{"error": {"code": "not_found", "message": "account acc_x not found"}}
```

| Status | Code | When |
|---|---|---|
| 400 | `bad_request` | semantically invalid input |
| 401 | `unauthorized` | missing, wrong, expired or revoked credential, or disabled user |
| 403 | `forbidden` | the user has a grant for the account but not for this operation (7.5) |
| 404 | `not_found` | account, folder, message, also an account the user has no grant for |
| 409 | `conflict`, `idempotency_conflict`, `credential_missing` | the last: the account has no credential of the kind its sign-in needs |
| 422 | FastAPI validation format | schema violation |
| 429 | `rate_limited` | with `Retry-After` |
| 501 | `not_supported` | capability missing |
| 500 | `credential_unreadable`, `storage_error` | a stored credential cannot be decrypted, the service's own database failed |
| 502 | `provider_error`, `provider_auth_failed`, `provider_unavailable` | upstream failed. An auth failure sets the account to `needs_reauth`, an unreachable server to `unreachable` |
| 503 | `setup_required` | neither a user nor `MAILBOX_SERVICE_KEY` exists yet |

### 6.8 OpenAPI

The API is OpenAPI 3.1, generated by FastAPI from the pydantic models.
Rules, all built and tested:

- `docs/openapi.json` is checked in. A test fails when it differs from
  the code. Regenerate with `benethos-mailbox-service openapi > docs/openapi.json`.
- `operationId` is the route function name (`list_messages`,
  `send_message`), unique and stable. Client generators and the MCP server
  depend on it.
- Every `/v1` operation declares the `bearerAuth` scheme and documents its
  error responses with the `ErrorResponse` schema.
- Every `/v1` operation declares its required right as `x-permission`
  (7.5).
- Interactive docs at `/docs` (Swagger UI) and `/redoc`.

## 7. Security

### 7.1 What has to be stored

| Secret | Where it comes from | Lifetime |
|---|---|---|
| IMAP / SMTP / POP3 password | the user, ideally an app password | until changed |
| OAuth refresh token (Gmail, Microsoft) | the OAuth callback | until revoked, may rotate on use |
| OAuth access token | refreshed from the refresh token | about one hour, **memory only** |
| OAuth client secret of our Google / Microsoft app | the operator | until rotated |
| API tokens of users | issued by the service, stored as hash only | until expired or revoked |

The MCP server holds **none** of these. It only holds its own REST token, in
the MCP client's configuration.

### 7.2 Threat model

Protected against:

- the database file or a backup of it being copied, synced to a cloud drive
  or left on an old disk
- secrets in logs, tracebacks, error responses and API responses
- secrets in a model's context, through the MCP server
- secrets in the repository, the container image or `docker inspect`
- a second ciphertext being swapped into another account's row

Not protected against, and not claimed: malware running as the same user
or as root on the same machine. It can ask the keyring for the key just as
the service does, or read the service's memory. Mail passwords have to be
usable unattended for background fetching, so something on the machine has
to be able to decrypt them. The design makes that *one* key, kept apart from
the data, rather than a readable file.

### 7.3 Design: envelope encryption

```
 key provider (keyring / secret file / env)
        │ KEK  256-bit key-encryption key, never stored next to the data
        ▼
 keys table:  key_id │ DEK encrypted with KEK        (SQLite)
        │ DEK  256-bit data key, decrypted into memory at start
        ▼
 credentials: account_id │ field │ key_id │ nonce │ AES-256-GCM ciphertext
                                            AAD = "{account_id}:{field}"
```

- **Cipher:** AES-256-GCM (`cryptography`, `AESGCM`) with a random 96-bit
  nonce per encryption. GCM rather than Fernet because GCM takes associated
  data: the account id and field name are bound into every ciphertext, so a
  password copied into another account's row fails to decrypt.
- **Two keys.** The DEK encrypts the secrets and lives, itself encrypted, in
  the database. The KEK only encrypts the DEK and never touches the
  database. A stolen database without the KEK is useless, and changing the
  KEK means re-encrypting one row, not every secret.
- **Key providers**, chosen with `MAILBOX_SERVICE_KEY_PROVIDER`:

  | Provider | Where the KEK lives | Default for |
  |---|---|---|
  | `keyring` | OS credential store via `keyring`: Windows Credential Manager (DPAPI, bound to the Windows login), macOS Keychain, Secret Service on Linux | service on the host |
  | `file` | a file outside the data directory, typically a compose secret at `/run/secrets/mailbox_service_master_key`, readable by the service user only | container |
  | `env` | `MAILBOX_SERVICE_MASTER_KEY` | tests, CI. Allowed but warned about at start, since the environment shows up in process listings and `docker inspect` |

  Only 32 bytes go into the keyring, well inside the Windows Credential
  Manager limit of 2560 bytes per entry. A passphrase-derived key was
  considered and left out: it would have to be typed after every start, and
  background fetching would stop whenever nobody did.
- **First start** creates KEK and DEK and prints a **recovery key** once
  (the KEK, base32-encoded, like a BitLocker recovery key). Without KEK and
  recovery key the credentials are gone, and every account has to be
  reconnected. The mail itself is not affected.
- **Rotation:** `benethos-mailbox-service keys rotate` re-wraps the DEK with a new
  KEK. `keys rotate --data` also re-encrypts every secret with a new DEK.
  `key_id` on each row lets old and new coexist during that run.

### 7.4 Handling rules

- **Input only through the management side.** Credentials reach the service
  through the REST API or its configuration UI, on loopback or over TLS.
  **There is no MCP tool that takes a password**, so a model never sees or
  types one. For a new account, the MCP server can at most hand out the link
  to the configuration UI.
- **Verify, then store.** A new or changed credential is tested against the
  provider first. Only a working one is encrypted and saved.
- **Write-only.** No route returns a secret. An account shows
  `credentials: {"type": "app_password", "updated_at": "..."}`, and `PATCH`
  replaces the value.
- **Short plaintext lifetime.** Secrets are `SecretStr` in every model,
  decrypted right before a login and handed to the protocol library, never
  cached in plain form. On a reconnect they are decrypted again, which is
  cheap. Python cannot wipe memory reliably, so this narrows the window and
  does not close it.
- **OAuth:** only the refresh token is stored. A rotated refresh token
  replaces the old one in the same transaction as the refresh. `invalid_grant`
  sets the account to `needs_reauth` and raises `account.needs_reauth`.
- **Logging:** `imaplib` debug output stays off, since it echoes the `LOGIN`
  command. A logging filter replaces every currently decrypted secret with
  `***` as a second line of defence. Provider error text is passed through
  the same filter before it goes into an API response.
- **Deletion:** removing an account deletes its credential rows.
  `PRAGMA secure_delete = ON` makes SQLite overwrite freed pages, so the
  ciphertext does not linger in the file.
- **Files:** the database sits in `data/benethos-mailbox-service/` in the
  working directory, moved with `MAILBOX_SERVICE_DATA_DIR`. Decided 2026-09-24:
  one folder per package under `data/` and under `config/`.
  `data/benethos-mailbox-mcp/` is meant for what the MCP server stores, e.g.
  downloaded attachments. A missing data folder is created. The database,
  a backup and a key file are created readable by their owner alone
  (0600) and never over an existing file. Windows has no such modes: there
  the folder's own permissions decide who may read them.
- **Credential kinds per provider:** always the one that is not the main
  password. Per provider in the table of 5.3. In short: OAuth for Google
  and Microsoft, an API token for Fastmail, an app password everywhere
  else.

### 7.5 Users, permissions and authentication

**Decided 2026-09-24:** callers of the REST API are **users** of the
service. Rights belong to the user. A bearer token is only one way for a
user to prove who it is.

Terms, since "account" is taken:

| Term | Meaning | Route |
|---|---|---|
| **Account** | a connected mailbox (GMX, Gmail, ...) | `/v1/accounts` |
| **User** | someone or something that calls the API: a person, the MCP server, a script | `/v1/users` |
| **Credential** | how a user authenticates: an API token today, more kinds later | `/v1/users/{id}/tokens` |
| **Grant** | a right of a user: which operations on which accounts | part of the user |
| **Role** | a named, reusable set of grants | `/v1/roles` |

```
 User "Claude Desktop"
   ├─ roles:  mail-reader
   ├─ grants: acc_gmx → mail.write, drafts
   └─ credentials
        ├─ token mbx_…a1  "laptop"   expires 2027-03-01
        └─ token mbx_…b7  "desktop"  expires 2027-03-01
```

#### Why users rather than tokens with rights

- **Several tokens, one set of rights.** A token per device or per
  installation, rotated one at a time without an outage. Revoking one does
  not touch the others, and rights are changed in one place.
- **Other ways to authenticate later** without touching the permission
  model: password with TOTP or a passkey for a person in the configuration UI,
  OAuth 2.0 client credentials for machines, mTLS behind a proxy. Each is a
  new credential kind of the same user.
- **The audit log names someone.** "Claude Desktop, token laptop, called
  send_message on acc_info" rather than an anonymous token id.
- **Several people** become possible without a second model. The open
  question of multi-user operation (section 12) shrinks to account ownership.

#### Example

| User | May |
|---|---|
| Owner | `admin` |
| Claude Desktop | `acc_gmx`: read and write mail, drafts. No other account. No sending |
| Dashboard | every account: read. Nothing else |
| Newsletter job | `acc_info`: `send_message` only |

As stored:

```json
{
  "id": "usr_7f3a",
  "name": "Claude Desktop",
  "roles": [],
  "grants": [
    {"accounts": ["acc_gmx"], "allow": ["mail.read", "mail.write", "drafts"]}
  ],
  "disabled": false
}
```

```json
{
  "id": "usr_91c0",
  "name": "Dashboard",
  "roles": ["mail-reader"],
  "grants": []
}
```

with the role

```json
{"id": "mail-reader", "grants": [{"accounts": ["*"], "allow": ["accounts.read", "mail.read"]}]}
```

#### The permission model

- **Permission unit = `operationId`.** Every route already has a stable,
  unique `operationId` (6.8), so it is the natural name of a right:
  `list_messages`, `send_message`, `delete_folder`. The finest level is one
  API call.
- **Groups** bundle operations so that ordinary grants stay readable. A
  grant may name groups, single operations or both:

  | Group | Operations |
  |---|---|
  | `accounts.read` | `list_accounts`, `get_account` |
  | `mail.read` | `list_all_messages`, `list_folders`, `list_messages`, `get_message`, `get_message_raw`, `get_attachment`, `list_threads`, `get_thread`, `list_changes` |
  | `mail.write` | `update_message`, `delete_message` to trash, `batch_messages`, `create_folder`, `update_folder` |
  | `mail.delete` | `delete_message_permanent` (`delete_message` with `permanent=true`), `delete_folder` |
  | `drafts` | `list_drafts`, `create_draft`, `update_draft`, `delete_draft` |
  | `send` | `send_message`, `send_draft` |
  | `audit` | `list_sends` |
  | `accounts.manage` | `create_account`, `update_account`, `delete_account`, `verify_account`, `discover_account`, credentials of mail accounts |
  | `webhooks.manage` | webhook routes |
  | `users.manage` | users, their tokens, roles. Not account-bound |
  | `admin` | everything |

  Permanent deletion and sending are their own groups on purpose: they are
  the two things that cannot be taken back.
- **Account level.** `accounts` is a list of account ids or `"*"`. `"*"`
  includes accounts added later, an explicit list does not.
- **Effective rights** of a user are the union of its direct grants and the
  grants of its roles. Default deny.
- **Check per request.** Credential → user → the route's `operationId` and
  the `account_id` from the path against the effective rights. Operations
  that carry an action in the body (`batch_messages`) are checked per action:
  a batch needs `batch_messages` and the right of the single operation
  (`update_message`, `delete_message` or `delete_message_permanent`).
- **Cross-account operations filter instead of failing.** `list_accounts`
  and `GET /v1/changes` return only accounts the user has a grant for.
- **No existence leak.** An account the user has no grant for answers `404`,
  as if it did not exist. A granted account with a missing operation
  answers `403 forbidden`, naming the missing right.
- **Every route declares its right.** Each operation carries `x-permission`
  in the OpenAPI document, and a test fails when a `/v1` operation has none.
  A new route cannot slip out unguarded.
- **No escalation.** A user with `users.manage` can only hand out rights it
  holds itself, so a delegated administrator cannot create anyone stronger
  than itself.
- **Constraints.** A grant can narrow further without changing the model:
  `recipients` (send only to `*@firma.de`) and `max_sends_per_day` come
  with the MCP send tools, since they are the main guard against prompt
  injection (7.7). `folders` (read only `INBOX` and `Rechnungen`) follows
  later.

  **Decided 2026-09-24:** `recipients` takes addresses, `*@domain` and `*`
  (anyone), without regard to case. A subdomain is named on its own.
  Constraints count per grant: a send is allowed when one grant that allows
  it on the account accepts every recipient and its limit is not reached.
  `max_sends_per_day` counts mails, whatever their number of recipients,
  that the user sent from the account in the last 24 hours, rolling.

  Rules of the implementation (phase 3):
  - Null means no constraint. Recipients are checked once the mail is
    composed: To, Cc and Bcc, and for a reply the recipients taken from the
    original. `send_draft` checks the stored draft.
  - A refused recipient answers `403 recipient_not_allowed`, a reached
    limit `429 send_limit_reached` with `Retry-After`. A retry with its
    `Idempotency-Key` returns the stored result and is not counted again.
  - Only sends with the outcome `sent` count. Sends of one user from one
    account run one after the other, so two cannot both pass the limit.
  - No escalation: a user with `users.manage` hands out `send_message` or
    `send_draft` only as narrow as one of its own grants for them, or
    narrower. The admin key has no constraints.

#### Credentials

- **API token**, the first and for now only kind:
  - Format `mbx_` + 64 random base62 characters, a little over 380 bits.
    Shown **once** on creation, stored as a SHA-256 hash (a random token of
    that length needs no slow hash).
  - Per token: `name`, `created_at`, `expires_at` (optional),
    `last_used_at`, `revoked_at`.
  - A token carries the rights of its user, no more. Narrowing a single
    token below its user is left open, since a second user with fewer
    rights does the same job.
- **Later:** password + TOTP or passkey for signing in to the configuration
  UI, OAuth 2.0 client credentials for machines. Which credential kinds a
  user holds decides where it can sign in. There is deliberately no "person"
  or "service" type on the user: rights come from grants alone, and a type
  field would only matter to rules nobody has asked for yet.
- A disabled user fails authentication with every credential at once.
  Rights changes take effect on the next request. Revoking a token is
  immediate.

#### Bootstrap

A fresh installation has no users. `benethos-mailbox-service users create-admin`
on the host creates the first `admin` user and prints its token once.
`MAILBOX_SERVICE_KEY` stays as an alternative for containers and tests: when
set, it authenticates as a built-in admin user. All further users and
tokens are created through the API.

#### Audit log

User, credential, operation, account, status, time. Never content, never a
secret.

**Decided 2026-09-24:** the audit of sends is built first, together with
the send limits, which count from it. Every attempt through `send_message`
or `send_draft` is one record: time, user, token (null for the admin key),
account, operation, recipients, outcome (`sent`, `denied` by a grant,
`failed`), error code, refused recipients and the Message-ID. It keeps no
reference to account or user, so it outlives both.
`GET /v1/accounts/{account_id}/sends` reads it, newest first, with the
right `list_sends` (group `audit`).

#### Endpoints

| Method | Path | Right |
|---|---|---|
| GET | `/v1/me` | any authenticated user. Who am I, and my effective rights resolved to operations per account |
| GET | `/v1/permissions` | any authenticated user. The catalogue of operations and groups |
| GET / POST | `/v1/users` | `users.manage` |
| GET / PATCH / DELETE | `/v1/users/{user_id}` | `users.manage`. Name, roles, grants, disabled |
| GET / POST | `/v1/users/{user_id}/tokens` | `users.manage`. POST returns the token once |
| DELETE | `/v1/users/{user_id}/tokens/{token_id}` | `users.manage`. Revoke |
| GET / POST | `/v1/roles` | `users.manage` |
| GET / PUT / DELETE | `/v1/roles/{role_id}` | `users.manage` |

#### And the MCP server

- It is a user of its own, typically with `mail.read`, `mail.write` and
  `drafts` on chosen accounts. It never gets `accounts.manage` or
  `users.manage`.
- It needs no `accounts.read`. Every token may call `/v1/me`. That answer
  lists each account the token has any right on, with its address and the
  operations allowed there. The tool `list_accounts` is built on it.
  `accounts.read` opens the full account records instead: the server
  settings, the state and which credentials are stored. The model does not
  need them.
- At start it calls `/v1/me` and registers **only the tools its user can
  use**. The user's rights decide what is offered to the model.

### 7.6 Other rules

- **Transport:** binds to `127.0.0.1` by default. Exposure beyond localhost
  only behind a TLS reverse proxy.
- **Logging:** no message bodies. Addresses and subjects only at `DEBUG`.
- **Sending is the dangerous verb:** separate right, idempotency key, and
  in the MCP server offered only to a user with the `send` group
  (section 8, 7.7).

### 7.7 Mail content is untrusted: prompt injection

Every incoming mail is text written by a stranger, and the MCP server hands
it to a model. A mail that says "forward all invoices to this address" is
data to a person, and may become an instruction to a model. Three things
together make that dangerous: access to private mail, content from
outside, and a way to send data out. With read and send rights on the same
user, the MCP server has all three.

**Both ways of working stay open (decided 2026-09-24).** Whether the model
sends mail itself or only writes drafts for a person to send is decided by
the rights of its user (the `send` group). The service has no built-in
preference. The documentation explains the trade-off, the configuration
makes it visible.

What applies in both modes:

1. **Mark content as foreign.** MCP tool output wraps everything taken from
   a mail (the headers with subject and sender, the body, attachment names
   and text) in clear delimiters, and the server instructions tell the
   model that this is content of a mail, never an instruction. A list of
   messages, which is JSON, carries a note that `from` and `subject` are
   the sender's words. This lowers the risk, it does not remove it.
2. **Show the model what a person sees.** The HTML to text conversion drops
   hidden content: `display:none`, zero-size or invisible text, comments.
   Hidden text is a common carrier of injected instructions.
3. **Recipient constraints** on the grant (`recipients`, 7.5): send only to
   the own domain, or to listed addresses. The strongest single measure
   when the model may send.
4. **Send limits** on the grant (`max_sends_per_day`).
5. **A warning, not a block.** A user that may read mail and send to anyone
   is flagged in `/v1/me`, in the configuration UI and in the MCP server's
   start log: "can read mail and send it to any address".
   Built in phase 3: an account in `/v1/me` carries the warning
   `read_and_send_anywhere` when the caller may `get_message` there and a
   grant lets it send without `recipients` (or with `*`). A send limit
   does not lift it.
6. **Audit.** Every send is logged with user, credential, account and
   recipients, never content, so it can be reviewed afterwards.
7. **Deleting** permanently is its own right (`mail.delete`), since an
   injected instruction can also destroy.

Recipient constraints and send limits therefore come with the MCP send
tools, not later (see [ROADMAP.md](ROADMAP.md)).

### 7.8 Backup and restore

**Decided 2026-09-24: required.** The service holds no mail, the providers
do. What it holds is everything needed to reach that mail: accounts, users,
rights, token hashes, encrypted credentials, the wrapped data key, id
mappings, sync state and the audit log. Losing it means reconnecting every
account and re-issuing every token.

- **`benethos-mailbox-service backup <file>`** takes a consistent snapshot while
  the service runs (SQLite online backup API) and adds a manifest: service
  version, schema version, key id, time, checksum.
- **The whole backup file is encrypted** (AES-256-GCM, key derived from the
  KEK), not only the credentials inside it. A stolen backup reveals not
  even the list of accounts.
- **The KEK is deliberately not in the backup.** Restoring needs the KEK on
  the same machine, or the **recovery key** from the first start (7.3).
  Keep backup file and recovery key in different places. Either alone is
  useless, which is the point.
- **`benethos-mailbox-service restore <file>`** refuses while the service runs,
  migrates an older schema forward, and refuses a newer one. On a new
  machine, `--recovery-key` also stores the KEK in the new key provider.
- **`benethos-mailbox-service backup verify <file>`** decrypts and checks a
  backup without restoring it. A backup that was never tested is a hope,
  not a backup.
- **Scheduled backups** optional, with a retention count, into a directory
  or the container volume.
- **After a restore** some OAuth refresh tokens may be stale, since
  providers rotate them. Those accounts go to `needs_reauth` and are
  reconnected once. API tokens are valid again as they were at backup time:
  if a backup leaked, revoke them.

## 8. MCP server

Its own distribution, `benethos-mailbox-mcp`, in the same uv workspace
as the service (**decided 2026-09-24**). It depends on `mcp` and `httpx`
only, never on the service package, so `uvx benethos-mailbox-mcp` stays
small and the REST-only rule is enforced by the dependency list itself. A
test checks that no module imports the service.

It reads `MAILBOX_SERVICE_URL` and `MAILBOX_SERVICE_TOKEN` and calls the REST API with
httpx. It runs over stdio or streamable HTTP. Over HTTP a bearer guard
admits clients with one shared token (`MAILBOX_MCP_BEARER_TOKEN`), which
is not passed on: the server acts as the user of its own API token, for
every client alike. Host and Origin are checked against DNS rebinding. At
start it asks `/v1/me` what its user may do, and only those tools exist
(7.5).

Tools are hand-written, not generated from OpenAPI: generated tools mirror
every parameter and cost far more context than they give. Each tool maps onto
one or two `operationId`s.

| Tool | Access | REST |
|---|---|---|
| `list_accounts` | read | `list_accounts` |
| `list_folders` | read | `list_folders` |
| `search_messages` | read | `list_all_messages` across accounts, or `list_messages` for one |
| `get_message` | read | `get_message`, body shortened, `max_chars` param |
| `get_thread` | read | `get_thread` |
| `get_attachment` | read | `get_attachment`: images as images, PDF pages as images, text types as text, other types by name only |
| `whats_new` | read | `list_changes` across accounts, the "what came in since" tool |
| `update_messages` | write | `batch_messages`: mark read, star, move, archive, trash |
| `create_folder` | write | `create_folder` |
| `list_drafts` | drafts | `list_drafts` |
| `create_draft` | drafts | `create_draft`, incl. reply / forward by reference |
| `update_draft` | drafts | `update_draft`, replaces the whole draft |
| `delete_draft` | drafts | `delete_draft` |
| `send_message` | send | `send_message`, with an idempotency key derived from the call |
| `send_draft` | send | `send_draft`, with an idempotency key derived from the call |

**Decided 2026-09-24, attachments:** `get_attachment` hands images over
as images, the pages of a PDF as PNG images (a page range, a few pages at
a time), text types as text inside the foreign-content marker, and other
types by name, type and size only. The conversion happens in the MCP
server. The API keeps handing out the attachment as it is. A PDF sent as
an embedded resource was refused by claude.ai in a test: it takes such a
blob for an image.

**Decided 2026-09-24:** sending a new mail and sending a draft are two
tools, `send_message` and `send_draft`. The model may create folders
(`create_folder`). Text from PDF attachments comes later. The policy file
stays as designed. The first tools go by the token's rights alone.

**Decided 2026-09-25:** no policy file. The token's rights, its grants and
their constraints decide which tools exist. The idea waits in IDEAS.md.

Principles:

- The **rights of the token** decide which tools exist (`/v1/me`).
  Whether the model may send or only draft is the operator's choice, both
  are supported equally (7.7).
- Mail content in tool output is marked as foreign content (7.7).
- Descriptions under 700 characters, compact output (no headers the model
  does not need, bodies truncated, HTML converted to text).
- Every error surfaces as an MCP `ToolError` with the REST error message.

### 8.1 Operation

**Decided 2026-09-24:** two processes with different lifetimes.

```
 Claude Desktop / Claude Code          (spawns on demand, one per client)
   └─ benethos-mailbox-mcp          stdio, short-lived, stateless
          │ HTTP 127.0.0.1:8080, bearer token
 benethos-mailbox-service serve             permanent service
   ├─ REST API
   ├─ background worker (sync, IDLE, change feed, webhooks)
   └─ SQLite: accounts, credentials, id mapping, sync state
```

- **The MCP server runs on demand:** a client spawns it over stdio, and it
  ends with the client. Streamable HTTP stays available
  for clients that connect to a URL instead.
- **The REST server runs permanently.** As a container (compose, bound to
  the loopback address) or as a background service on the host (`serve`,
  started at login).

**Decided 2026-09-24, container:** the image is built by GitHub Actions for
`linux/amd64` and `linux/arm64` and pushed to the GitHub container
registry. The master key reaches the container as a file secret. Image
files and the compose file live in `containers/`, one folder per image.

Rules of the implementation (phase 3): the image holds the service package
only, installed from the lockfile, and runs as a non-root user on a
read-only root file system. Configuration comes from the environment, the
database from the volume `/data`. `keys generate` prints a new master key
for the secret file, and `keys init` then adds the data key. The compose
file publishes the port on `127.0.0.1` only. See the "Container" sections
of the package READMEs.

Why the REST server cannot be spawned per session like an MCP server:

1. **Background fetching.** New mail, the change feed, `whats_new` and
   webhooks need something that watches the mailboxes while no client is
   open: IMAP IDLE or polling, Gmail `history.list`, Graph delta queries.
2. **Connection limits.** Providers limit simultaneous IMAP connections per
   account. Every open Claude window spawns its own stdio process, so
   connections per process would multiply. One service owns one connection
   per account and all clients share it.
3. **Cost per login.** An IMAP login with TLS takes seconds. A permanent
   service logs in once and keeps the session.
4. **OAuth callbacks** for Gmail and Microsoft need a server that is
   listening when the browser redirects back.
5. **Shared state.** Id mapping, idempotency keys and sync state belong to
   one owner, not to several short-lived processes.

What the worker does and does not do: it keeps sync state, the id mapping
(4.1) and the change feed current.

**Decided 2026-09-24:** the worker watches the inbox of an IMAP account
over IDLE and polls the other folders, every 5 minutes by default,
configurable. A poll asks each folder for its state and reads only the
folders whose state changed. It does **not** mirror mailboxes. List, search
and get still go to the provider live, unless the local cache of open
question 5 is decided.

**Fallback without the service**, for development and tests only:
a test harness can run the service app and the MCP client in one process
via `httpx.ASGITransport`. The REST contract stays the same, there is just
no network hop and no background fetching. It is not offered as a user
mode, since it would put the service package into the MCP installation.

## 9. Technology

| Area | Choice |
|---|---|
| Python | 3.11–3.14 |
| Packaging | uv workspace with two distributions, hatchling, `src/` layout |
| Web | FastAPI, uvicorn, pydantic v2, pydantic-settings |
| Storage | SQLite (stdlib `sqlite3` via a thread, or `aiosqlite`) |
| Crypto | `cryptography` (AES-256-GCM), `keyring` |
| Mail | IMAPClient, imap-tools (parser), smtplib, poplib, httpx (Gmail, Graph) |
| MCP | `mcp` 2.x |
| Quality | pytest, pytest-asyncio, pytest-cov (≥ 80 %), ruff, mypy, GitHub Actions |
| Container | non-root image, compose file bound to the loopback address |

## 10. Testing

- **Offline suite is the gate.** No test reaches a mail server.
- API tests run against the `memory` adapter through `TestClient`.
- IMAP adapter tests use a fake `IMAPClient` object at the library boundary.
  Additionally a Stalwart container, which speaks IMAP, SMTP and JMAP,
  for an optional integration job (5.6).
- Gmail and Graph adapter tests use `httpx.MockTransport` with recorded,
  anonymized response shapes.
- `live/` holds manual smoke scripts, outside `testpaths`. They run
  against **test accounts on an IMAP server of our own**. Its address and
  the list of test accounts are local, unversioned configuration, and only
  accounts listed there count as confirmed test accounts (golden rule 1 in
  CLAUDE.md).
- The traps of 5.10 (folder names in modified UTF-7, localised special
  folders, broken charsets, IDN, SMTPUTF8) get fixtures of their own.
- Contract tests: committed OpenAPI document, unique `operationId`s, bearer
  and error responses on every protected route.

## 11. Roadmap

Moved to [ROADMAP.md](ROADMAP.md).

## 12. Open questions

Undecided ideas are collected in [IDEAS.md](IDEAS.md).


1. **Deployment:** decided, see section 8.1. Still open is whether the
   service later serves several people. Users and grants (7.5) already
   separate callers. What would remain is an owner on each mail account,
   so that one person's administrator cannot grant rights on another's
   mail.
2. **Name:** decided 2026-09-24: repository `mailbox-service`, distributions
   `benethos-mailbox-service` and `benethos-mailbox-mcp`, environment prefix
   `MAILBOX_SERVICE_`. A descriptive name rather than a brand: it says what the
   service is, and cannot collide with anyone's trademark. "Mail gateway"
   was ruled out because it already names a different kind of product,
   the filtering gateway in front of a mail server.
3. **Gmail / Microsoft priority:** are they needed early, or are GMX / web.de
   / T-Online over IMAP the main use?
4. **Sending from the MCP server:** decided 2026-09-24, both stay open,
   governed by rights (7.7).
5. **Local cache:** list and search go straight to the provider in the
   design above. A local index (SQLite FTS) would make search across all
   accounts fast, at the cost of a sync engine. Decide after phase 3.
