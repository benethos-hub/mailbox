# Concept: purpose and model

Part of the [concept](../CONCEPT.md): sections 1 to 4.

## 1. Purpose

One REST API in front of many mail accounts at many providers. A client
talks to `/v1/accounts/{account_id}/...` and never learns whether the account
is Gmail, Microsoft 365, GMX over IMAP or a POP3 mailbox. On top of the API
sits an MCP server, so an assistant can read, search, triage and send mail
across all connected accounts.

Two layers, strictly separated, and between them the Python client
`mailbox-client` (8.2), which the MCP server and any script use:

```
 MCP client (Claude, ...)
        │  MCP (stdio / streamable HTTP)
 ┌──────▼───────────┐
 │  MCP server      │  thin: tools → calls of the client, compact output
 └──────┬───────────┘
        │  HTTPS + bearer token        ◄── the OpenAPI document is the contract
 ┌──────▼───────────┐
 │  REST API        │  FastAPI, /v1, OpenAPI 3.1
 │  account store   │  SQLite, credentials encrypted
 │  adapters        │  imap · pop3 · jmap · gmail · microsoft
 └──────┬───────────┘
        │  IMAP/SMTP · POP3 · JMAP · Gmail API · Microsoft Graph
    mail providers
```

The MCP server never imports an adapter. Everything it can do, any other
REST client can do too.

### 1.1 Inside the service

**Decided 2026-09-24:** three layers, imports only point down.

```
 web/          PRESENTATION ─ HTTP only
   api/          JSON API under /v1  ◄── scripts, apps, the client, the MCP server
   pages/        configuration UI    ◄── a person in the browser
      │  who is calling (token or session) → the domain
 domain/       BUSINESS LOGIC ─ no HTTP, one package per area
   rights · auth · users · accounts · discovery · mailbox
   sync · changes · webhooks · system · activity
      │
 data/         DATA ─ decides nothing, one package per kind
   models/     provider-neutral types, one module per subject
   mail/       messages in RFC 5322: compose, parse, convert
   protocols/  the wire, one library each: IMAP, POP3, SMTP, JMAP, OAuth,
               and http/:
               the SSRF guard, JSON to known hosts, webhook posts
   providers/  imap · pop3 · jmap · microsoft · gmail · memory,
               behind a registry
   storage/    own records: accounts, users, credentials
   secrets/    envelope encryption, key providers, password hashes
   discovery/  autodiscovery sources
   backup.py, files.py, logbook.py
 common/       CROSS-CUTTING ─ helpers every layer reads: cursors,
               the clock, pacing. config.py and errors.py sit
               next to the layers
```

**Decided 2026-09-28:** the domain is in packages by area
([REFACTORING.md](../REFACTORING.md)). A package imports only packages on
a lower line, through their `__init__.py`:

```
 system                      status, recovery key, log page
 mailbox · users · webhooks  mail and sending, users, posts to webhooks
 sync                        stable message ids, the sync pass, IDLE
 accounts                    accounts, their live adapter, OAuth
 auth · discovery · changes  sign-in, autodiscovery, the change feed
 activity                    what was done, for the log
 rights                      who may do what
```

The data layer the same way (REFACTORING.md section 8):

```
 backup                           encrypted backups of the database
 secrets                          cipher, keys, password hashes, the vault
 storage · providers · discovery  own records, the adapters, autodiscovery
 protocols                        the wire: IMAP, POP3, SMTP, JMAP, HTTP, OAuth
 mail · files                     messages in RFC 5322, files for the owner
 models · logbook                 the neutral types, the newest log lines
```

- **Two front ends, one domain.** The JSON API and the configuration UI are
  both part of the web layer and both call the same domain services. The UI
  is not a client of the API over HTTP. It runs in the same process and
  skips the network hop, but it goes through the same domain, and so through
  the same checks.
- **Rights are enforced in the domain.** The web layer only establishes who
  is calling: a bearer token on the API, a session after password login in
  the UI (7.5). What that user may do is decided once, in the
  domain, for both front ends.
- **The configuration UI** covers what a person has to do by hand:
  connecting accounts and entering app passwords, the OAuth round trip for
  Microsoft and Gmail, users, roles and tokens, webhooks, the recovery
  key, the service log, and a status view of accounts and sync.
  Server-rendered pages, not in the OpenAPI document, under `/ui`. Forms
  carry CSRF protection, since a session cookie authenticates them.

  **Decided 2026-09-24:** the UI comes before the new providers and covers
  everything the REST API does. Its texts are English. Built with Jinja2
  templates, htmx and one stylesheet, without a build step.

  **Decided 2026-09-27:** a person signs in to the UI with a user name and
  a password (7.5), no longer with an API token. Tokens are for the API
  and the MCP server alone.

  How the pages look and behave, and the rules a new page follows, are
  in [UI.md](../UI.md).

  Rules of the implementation: the session lives on the server, the cookie
  (`HttpOnly`, `SameSite=Strict`, path `/ui`) carries only a random id, and
  the session holds the id of its user. Every request loads that user
  anew, so a disabled or deleted user is signed out at once. Signing in
  starts a new session. A changed password ends every other session of
  its user. Sessions end after 8 hours (a setting) without a request,
  after 24 hours however used, and with a restart. A user holds 10 at
  most, and a new sign-in ends the oldest. A content security policy allows no inline script or style and
  no framing. A form answers with a redirect (Post/Redirect/Get). Its
  message waits in the session and is shown once, never in the URL, so a
  link cannot put words into the UI. The sign-in page, which has no
  session, names one of its own messages by a code.
  Guessing is slowed down: a client address that fails to sign in ten
  times within fifteen minutes is locked out for fifteen minutes, on the
  UI and on the API alike, whatever the credential kind. A valid API
  token passes regardless, since it cannot be guessed. A user name that
  fails ten times within fifteen minutes waits one minute, from any
  address. The numbers are settings. That slows guessing at one account spread over many addresses,
  and never locks its owner out for long. Requests are limited as
  well: 120 a minute per API token or UI session, 30 a minute per client
  address for requests without a credential, each with a burst of half
  as many, answered with `429` and `Retry-After`. Every limit and how
  they work together: [LIMITS.md](../LIMITS.md).
  Behind a proxy, `MAILBOX_SERVICE_FORWARDED_ALLOW_IPS` names the proxy
  so the client address comes from `X-Forwarded-For`.
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
- **Every mailbox is operated the same way.** What an account cannot do
  answers `501`, announced by its capabilities (5.11).

## 4. Resource model

| Resource | Notes |
|---|---|
| **Account** | one mailbox at one provider. `id` is ours (`acc_…`). Carries `provider`, `email`, `status` (`connected`, `needs_reauth`, `unreachable`), `capabilities` and `marks` (5.11), and `operations`, what the caller may run there (7.5). |
| **Folder** | `id`, `name`, `role` (RFC 6154 special use: inbox, sent, drafts, trash, junk, archive, all), `parent_id`, counts, `subscribed` (IMAP, decided 2026-09-24). Gmail labels are folders. |
| **Message** | summary (list) and full form (get). `folder_ids` is an array. `unread`, `starred` as booleans, further flags as `keywords`. |
| **Thread** | the provider's own on Gmail, JMAP and Microsoft. On IMAP built by the service across folders from `Message-ID`, `In-Reply-To` and `References` (6.3). None on POP3. |
| **Attachment** | metadata on the message, content via its own download route. |
| **Draft** | a message with the draft role, own routes because providers treat it specially. |
| **Change** | an entry in the change feed: `{type, id, account_id, at}`. |
| **Webhook** | callback URL + event list + signing secret. |
| **Token** | an API token of a user. It carries the user's rights, no more (7.5). |

### 4.1 Message ids

Our id must be stable across moves, because a client (and a model) keeps it
between calls. Per adapter:

| Adapter | Source of stability |
|---|---|
| Gmail | Gmail message id, stable by design |
| Microsoft | Graph with `Prefer: IdType="ImmutableId"` |
| JMAP | the JMAP email id, immutable by the standard |
| IMAP | our own id mapped to `(folder, UIDVALIDITY, UID)` in the store, updated when *we* move a message and re-resolved by `Message-ID` header when the mapping breaks. `OBJECTID` (RFC 8474) is not read |
| POP3 | our own id mapped to the `UIDL` of the one folder. The ids never move (5.2) |

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
- **A change of ours during a pass.** A sync pass that a change made
  through the service overtook applies nothing and reads again, three
  times at most.
- **A list before the sync.** A list that meets a message in a place
  the index does not know, with a `Message-ID` the index has
  elsewhere, syncs the account once before it gives the message an
  id: another program may have moved it, and it keeps its id
  (decided 2026-11-19). A message the service stored itself a moment
  ago, a draft or a sent copy, gets its id without that.
