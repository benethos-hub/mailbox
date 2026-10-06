# Changelog

All notable changes to this project are documented here. The format follows
[Keep a Changelog](https://keepachangelog.com/en/1.1.0/), and the project
adheres to [Semantic Versioning](https://semver.org/).

## [Unreleased]

### Added

- `service` on users and roles, in `POST`, `PATCH` and `PUT`: rights of
  the service, bound to no account. `accounts.connect`, `users.read`,
  `users.manage`, `webhooks.manage` and `admin` belong there, or single
  operations of them. `/v1/permissions` lists these groups as `service`.
- `accounts.connect`: `discover_account`, `start_oauth` and
  `create_account`, which were part of `accounts.manage`.
- `users.read`: `list_users`, `get_user`, `list_tokens`, `list_roles` and
  `get_role`, to see users and roles without changing them. `users.manage`
  keeps every right it had.
- Whoever connects an account gets `accounts.manage` on it, unless it
  holds that there already.
- `expires_at` on a grant, with a time zone, null for never. An expired
  grant grants nothing and stays until it is removed. A grant is handed
  out for no longer than the giver holds it. The editor has a field
  "Valid until", and the user's page marks an expired grant.
- `/v1/me` gives each account a `sending` list, one entry per grant that
  allows sending there: its `recipients`, `max_sends_per_day` and
  `sends_left`, how many more the limit allows now.
- The MCP server's `list_accounts` names these limits beside `send`, and
  warns of an account where the token may read mail and send it anywhere.
- The UI's New role page offers four templates that fill the form:
  Reader, Agent, Sender and Operator.
- `folders` on a grant: reading, writing and deleting mail only in these
  folders and their subfolders, named by role, name or id. A message or
  folder outside answers `404`, a move or a new folder outside `403`.
  Deleting to the trash stays allowed, reading the trash needs it in the
  list. Folder lists, message lists, the change feed and webhooks leave
  out the rest, and a reply or forward needs its original in reach. The
  editor has a field "Only in the folders".
- `GET /v1/audit` (`list_activity`): the audit of administration, newest
  first. Sign-ins, failed ones and refused tokens, and who changed users,
  passwords, tokens, roles, accounts and webhooks, with the user, the
  credential, the client address, the record touched, the outcome and
  what was done. Never a secret, never mail content, and a failed sign-in
  with a name that is no user's keeps no name. Filters `user`,
  `activity` (a name or its area), `record`, `after`, `before`. Kept for
  `MAILBOX_SERVICE_AUDIT_DAYS` days, as the audit of sends.
- `audit` in `service` reads it. `audit` in a grant stays the audit of
  sends. `/v1/permissions` lists `audit` among the groups of the service,
  with `list_activity` in the group.
- The UI has a page Audit under Service, and a user's page a card Recent
  activity, both for `audit` in `service`.
- Filters on the lists, as the UI has them. Each is optional, and a list
  without one answers as before. `GET /v1/sends` and
  `GET /v1/accounts/{id}/sends`: `user`, `outcome`, `recipient` (part of
  an address), `after` and `before` (a time with a zone).
  `GET /v1/users`: `name` (part of it), `role`, `disabled`, `ui_sign_in`.
  `GET /v1/accounts`: `address` (part of it), `provider`, `status`.
  `GET /v1/webhooks`: `url` (part of it), `account`, `failing`.
- A user in the answers of `/v1/users` says how it signs in to the UI:
  `has_password`, `must_change` (a password set for it, to be changed at
  the next sign-in) and `last_sign_in_at`. The schema is `UserInfo`, the
  fields of `User` and these three. The user's page in the UI names a
  password still to be changed.
- The UI shows a message's keywords in the list and adds or removes them
  on the message. Those starting with `$` stay as they are.

### Changed

- The UI's filters have the API's query names: `user` on Sends and
  Audit, `recipient` on Sends. A kept link with `who` or `to` no longer
  filters.
- Minimum versions without a known vulnerability. `benethos-mailbox-service`:
  fastapi 0.133.0, starlette 1.3.1 (now named, fastapi asks for no safe
  version), python-multipart 0.0.31, cryptography 50, anyio 4.14.2,
  jinja2 3.1.6, dnspython 2.6.1. `benethos-mailbox-mcp`: starlette 1.3.1,
  anyio 4.14.2. An install from the lockfile, as the images do, had them
  already.
- The project is named Mailbox, its packages `mailbox-service` and
  `mailbox-mcp`. The OpenAPI document's title is `mailbox-service`, the
  MCP server's `mailbox-mcp`. On PyPI and ghcr.io the names stay
  `benethos-mailbox-service` and `benethos-mailbox-mcp`.
- A right of the service or `admin` in a grant's `allow` answers `400`,
  and a right on accounts in `service` as well. Stored rights move at the
  first start: what a grant named of the service goes to `service`, a
  grant with `accounts.manage` on every account gets `accounts.connect`.
  Nobody loses a right. The log names each user and role whose rights
  moved.
- `accounts.manage` is about existing accounts alone: `update_account`,
  `delete_account` and `verify_account`.
- On an IMAP server that keeps every folder below the inbox, such as
  `INBOX.Sent`, the folders right below it are at the top, as mail
  clients show them: `parent_id` is null for them. Their ids stay.
- A change that would leave no enabled administrator who can sign in to
  the UI answers `409`: disabling, deleting, taking `admin` or the UI
  sign-in away, directly or through a role. Where there is none to begin
  with, nothing is held back. `users set-password` on the host stays the
  way back.

## [0.2.0] - 2026-10-03

The status is alpha: usable with real accounts for testing. The API and
the configuration may still change. Stored data is carried forward by
migrations.

### Added

- `MAILBOX_SERVICE_AUDIT_DAYS` (90): how long the audit of sends keeps a
  record. `0` keeps every record, as before. Old records are purged as a
  send comes in, once an hour at most, and the log names the count.
- `MAILBOX_SERVICE_SYNC_WATCHERS` (50): how many accounts the sync worker
  watches over IMAP IDLE at once. Further accounts are polled only, and
  the log says so once per account.
- Requests are limited: 120 a minute per API token or UI session, and 30
  a minute per client address for requests without a credential, each
  with a burst of half as many. Past the limit the service answers `429`
  `rate_limited` with `Retry-After`. `/health` is not limited. Set by
  `MAILBOX_SERVICE_RATE_LIMIT_PER_MINUTE` and
  `MAILBOX_SERVICE_RATE_LIMIT_ANONYMOUS_PER_MINUTE`, `0` switches a
  limit off. Behind a reverse proxy set
  `MAILBOX_SERVICE_FORWARDED_ALLOW_IPS`, or every visitor counts as the
  proxy's address.
- `MAILBOX_SERVICE_IMAP_REQUESTS_PER_MINUTE` (60) and
  `MAILBOX_SERVICE_IMAP_BURST` (10): how fast the service sends requests
  to an account's IMAP server. An account's `max_requests_per_minute`
  still wins over the rate.
- Every other limit is a setting too, with the value it had:
  `MAILBOX_SERVICE_SIGN_IN_FAILURES` (10) and
  `MAILBOX_SERVICE_SIGN_IN_LOCKOUT_MINUTES` (15) for the lockout of a
  client address, `MAILBOX_SERVICE_SIGN_IN_NAME_WAIT` (60 seconds) for a
  user name, `MAILBOX_SERVICE_PASSWORD_HASHES_AT_ONCE` (2),
  `MAILBOX_SERVICE_SESSION_IDLE_HOURS` (8),
  `MAILBOX_SERVICE_DISCOVERY_PER_MINUTE` (10 per user),
  `MAILBOX_SERVICE_IMAP_ATTEMPTS` (3), `MAILBOX_SERVICE_IMAP_FIRST_PAUSE`
  (30 seconds) and `MAILBOX_SERVICE_IMAP_LONGEST_PAUSE` (900) for a
  server that does not answer. `docs/LIMITS.md` has every limit.

- A log page in the UI under Service, for a user with `admin` on every
  account: the newest 1000 lines of the service log since the start,
  newest first, with a search and the least level. Secrets are masked.
  The right `read_service_log` comes with `admin` alone and cannot be
  granted by name.
- `--env-file PATH` for every command of the service, before or after
  the command, and `MAILBOX_SERVICE_ENV_FILE`: the settings file to read.
  A file named this way must exist, and relative paths in the settings
  count from its folder. `serve` names the settings file it read at
  start.
- `GET /v1/sends` (`list_all_sends`, in `audit`): the audit of sends of
  every account the caller may audit, newest first, as the UI's sends
  page shows it.
- `GET /v1/webhooks/{webhook_id}` (`get_webhook`, in `webhooks.manage`):
  one of the caller's webhooks with its last 20 posts, each with the
  number of events, the receiver's answer and the error.
- `POST /v1/users/{user_id}/password` (`set_password`, in
  `users.manage`): a password for a user with UI sign-in, to be changed
  at its next sign-in. Without a password in the request the service
  makes a one-time password and answers it once. The rules are those of
  the UI: the caller covers the user, and neither the caller itself nor
  an API user gets one (`409`).
- `ui_sign_in` on a user, in `POST /v1/users`, `PATCH
  /v1/users/{user_id}` and every user in an answer: whether it may sign
  in to the configuration UI. Without it the user is an API user and
  works with tokens only. Switched off, its password is deleted and its
  UI sessions end. The UI asks for it when a user is made, shows API
  users with a tag and filters by it.
- Webhooks in the configuration UI: a list with the state of each, a
  page to create one that shows its secret once, and a page per webhook
  with its last deliveries. The service keeps the last 20 posts of each
  webhook: when, how many events, the receiver's answer and the error.
- A status page in the UI: each account with its status, last sync and
  last error, the sync worker, and the user's webhooks. It asks no
  provider. The sync state is kept in memory, so it starts empty.
- A recovery key page in the UI, for a user with `admin` on every
  account. It shows the key once, after the password is typed again, and
  the service log notes to whom. The right `show_recovery_key` comes
  with `admin` alone and cannot be granted by name.
- A change feed: `GET /v1/accounts/{account_id}/changes` and
  `GET /v1/changes` (`list_changes`, `list_all_changes`, both in
  `mail.read`) name each message created, updated or deleted since a
  `state`, oldest first, ids only. Without `since` the answer holds only
  the current state. `more` says to ask again at once. A state the feed no
  longer knows answers `410 changes_expired`. Changes come from the sync
  (IMAP), from Graph delta queries (Microsoft) and from the API.
- `MAILBOX_SERVICE_CHANGES_DAYS`: days a change is kept, 7 by default.
- On an IMAP server with CONDSTORE, flags another mail client changes
  reach the change feed as `message.updated`.
- Microsoft accounts reach the change feed: the sync worker now polls
  them too, at `MAILBOX_SERVICE_SYNC_INTERVAL`, with one Graph delta query
  per folder.
- Webhooks: `POST /v1/webhooks` registers a URL for events,
  `GET /v1/webhooks` lists the caller's own, `DELETE
  /v1/webhooks/{webhook_id}` removes one, all under the new right
  `webhooks.manage`. The answer to `POST` holds the signing secret, the
  only time it is shown. A host in the local network is allowed. Events:
  `message.created`, `message.updated`, `message.deleted`, `message.sent`
  and `account.needs_reauth`.
- The service posts events to each webhook, up to 100 in one JSON post,
  signed in `X-Mailbox-Signature` as `t=<unix time>,v1=<hex>`, the
  HMAC-SHA256 of `<unix time>.` and the body with the webhook's secret.
  A post the receiver does not answer with 2xx is tried again after 30
  seconds, then twice as long each time up to an hour, 8 times in all.
  Then its events are dropped and `last_error` says so. The settings
  `MAILBOX_SERVICE_WEBHOOK_ATTEMPTS`, `_FIRST_RETRY`, `_LONGEST_RETRY` and
  `_TIMEOUT` change that. Link-local, multicast and unspecified addresses
  are refused, redirects are not followed.
- The MCP tool `whats_new`: mail created, updated or deleted since the
  `state` of an earlier call, in one account or all. A token with
  `mail.read` gets it.

- The configuration UI signs in with a user name and a password. A user
  changes its own password under **Password** with the current one. A
  user with the new right `set_password` (in `users.manage`) sets another
  user's password on its page, within its own rights. That user must
  change it at the next sign-in. A changed password signs out every
  other session of its user. Passwords have 15 to 256 characters.
- A wrong user name and a wrong password answer alike. After ten failures
  in fifteen minutes a user name waits one minute, from any address, on
  top of the lockout per client address.

### Changed

- Every log line writes the time alike: ISO 8601, local, to the
  millisecond, with the offset, such as `2026-09-30T10:12:22.123+02:00`.
  The plain lines had a space instead of the `T`, the terminal and the
  log page no offset, a time inside a line was in UTC. The MCP server's
  log had no time at all.
- An `Idempotency-Key` sent before this version and sent again within
  its 24 hours answers `409 idempotency_conflict`, as if the request had
  changed: a request is fingerprinted anew. A `next_cursor` of the lists
  across accounts from before is refused once as belonging to another
  search. Start such a list again without the cursor.
- The service log writes what was done as one sentence per activity,
  each under a name of its own, `activity.<area>.<name>`, such as
  `activity.auth.signed_in` or `activity.users.token_revoked`. The areas
  are the parts of the service, and docs/LOGGING.md lists every name.
  The console and the log page show the source without the package's
  name. A line says who, what, to which record, from which client
  address, and why. A
  caller with a token is named with the token's name. `serve` logs where
  its settings came from, the database and its schema when it starts,
  instead of printing them, and logs when it stops. A migration of the
  schema is logged at start with its notes. Users, tokens, roles and
  accounts are logged when they are created, changed or removed, an
  OAuth sign-in when it starts, finishes or fails, an account's status
  when it changes, and a token that is refused because it is revoked or
  expired. A sent mail names the count of its recipients, a refused or
  failed send the error's code, never an address. Webhooks are logged
  when created or removed and when a post fails, gives up or goes
  through again, never with their URL. Each limit is logged once when it
  engages: a client address locked out after failed sign-ins, a user
  name slowed down, the discovery and the send limit, a request body too
  large. At `DEBUG` each sync pass with its counts, IDLE renewed, a token
  refreshed, a discovery by its domain, an Idempotency-Key replayed.
- A technical line of the service names its module in the package it
  moved to, such as `domain.sync.worker` for `domain.worker`.
- The MCP server logs at start which tools it serves, over which
  transport, for which service, and a warning for each tool that fails,
  with the tool's name and the service's error code, never its
  arguments. The MCP library logs from `WARNING` on, like httpx.
- The MCP server refuses a `MAILBOX_MCP_LOG_LEVEL` or `MAILBOX_MCP_PORT`
  it cannot use with a message, as it does `MAILBOX_MCP_TRANSPORT`.
  Before, it stopped with a traceback.
- The MCP server does not start without `MAILBOX_SERVICE_TOKEN` and
  names the variable. Before, it stopped with the service's `401`.
- The health check of the service image asks the port
  `MAILBOX_SERVICE_PORT` names. Before, another port made the container
  unhealthy for good.
- In `compose.yaml` the allowed Host values of the MCP server follow
  `MAILBOX_MCP_PORT`. Before, another port answered `421`.
- An HTML attachment reaches the model of the MCP server as the text a
  reader sees, as an HTML body does. Before, it came as markup with its
  hidden parts.
- `list_drafts` of the MCP server carries a `note` that `to` and
  `subject` may be the words of the mail a draft answers, as
  `search_messages` does for `from` and `subject`.
- The MCP server leaves out more hidden text of an HTML mail: a font
  below 2px, opacity below 0.1, text pushed far off the page, a box of
  height 0 with its overflow hidden, and text in the colour of its own
  background.
- The MCP server tells a slow answer of the service from a service that
  is not running: a request waits 30 seconds, an attachment 120. Before,
  a timeout said the service was not reachable.
- `update_draft` with the draft as it is stored, every attachment kept,
  stores nothing and answers the stored draft. Before, the provider
  stored it again. The UI did this check on its own so far.
- The OpenAPI document names `400` and `409` on every route under `/v1`,
  as the service answers them.
- A refused editor in the configuration UI is shown again with what was
  typed and the reason, and answers `400`: users, tokens, roles, an
  account's settings, webhooks and folders. The password is left out.
  Before, it went back to an empty editor with the reason alone.
- A cursor from another folder of an IMAP account answers
  `invalid cursor`, like every other cursor the service did not hand out.
- A new user is an API user unless `ui_sign_in` is set. Existing users
  with a password keep their UI sign-in, those without are API users.
  Setting a password for an API user is refused with `409`.
  `users set-password` on the host switches the UI sign-in on.
- The configuration UI has a lighter, bluish look. The sidebar shows only
  the pages the signed-in user may open, grouped as Mailboxes and
  Service.
- The overview of the UI starts with the signed-in user: roles, rights
  and the sign-in before this one. For a user who may list accounts it
  names the accounts that need attention, failing webhooks and the sync
  worker's last pass.
- Connecting an account in the UI starts with the address alone. The
  ways found follow, the recommended one first, setting up by hand
  folded below them. A refused connect shows the page again with what
  was typed, the reason under the password. An account's page shows its
  last sync, and an OAuth account can change its display name.
- A new user in the UI can get a one-time password, made by the service
  and shown once, to be changed at the first sign-in. A user's page
  shows its last sign-in. A new role has a page of its own.
- Every list in the UI that filters has the same filter bar: a search
  field, more filters folded, the active ones as chips that remove
  themselves. A page below another names the way back in a breadcrumb,
  a message has a link back to its list.
- Sends, users, accounts and webhooks in the UI have that filter bar.
  Sends are one list for every account the user may audit, filtered by
  account, who, outcome, days and recipient, and paged across accounts.
  `/ui/accounts/{account_id}/sends` leads there.
- The configuration UI no longer takes an API token to sign in. Tokens
  are for the API and the MCP server.
- `users create-admin` prints a one-time password instead of a token. The
  first sign-in to the UI asks for a password of one's own. A second user
  of the same name is refused. `users set-password NAME` gives a user a
  new one-time password, e.g. when the last administrator forgot theirs.
- The last two places with the old name use the new one. A draft marks
  what it replies to with `X-Mailbox-Service-Reference` (was
  `X-Mailbox-Api-Reference`), and a backup starts with
  `MAILBOX-SERVICE-BACKUP 1` (was `MAILBOX-API-BACKUP 1`). A backup
  made by 0.1.0 is refused. A draft saved by 0.1.0 loses its reference,
  and the old header stays in the mail when that draft is sent.
- User names are unique regardless of case, since a person will sign in
  with one. The database moves to schema 9. Of two users with the same
  name, the later one gets part of its id appended.

### Removed

- IMAP accounts with `auth: xoauth2` answer `501 not_supported`. Nothing
  renewed their access token, so the login was rejected within the hour
  and the account blocked. They come back with a token refresher.
- The built-in admin key `MAILBOX_SERVICE_KEY`. Every call is made by a
  user, so the audit names one. Make the first user with
  `users create-admin` and a token for the API on its page in the UI. A
  send from the UI has no token in the audit (`credential_id` null).

### Fixed

- A watched account no longer holds a thread of the pool that answers
  requests while it waits in IDLE. With many IMAP accounts, requests and
  pages of the UI had to wait for a free thread.
- The compose file caps the log Docker keeps of each container at 5
  files of 10 MB. Before, the log grew for as long as the container ran.
- The database file shrinks after an account is removed or old records
  are purged. Before, it stayed at its largest size for good. A database
  made by an earlier version is rewritten once when the service opens it,
  which takes a moment for a large one, and the log says so.
- A host in `MAILBOX_SERVICE_DISCOVERY_INTERNAL_HOSTS` matches however
  it is written, in Unicode or in punycode. Before, an internal host
  written in Unicode was refused as non-public when an account or
  autodiscovery named it in punycode, and the other way round.
- A command that cannot build the service, such as `serve` with a
  client secret file that is missing, closes the database again before
  it stops. Before, the connection stayed open until the process ended.
- The service log holds what the service writes. `serve` left the
  service's own records without a handler: sign-ins to the UI and
  changes to users were dropped, and warnings came without time or
  source. Now every line of the service and of uvicorn goes to stderr
  with time, level and source, at `MAILBOX_SERVICE_LOG_LEVEL`. The
  access log goes there too, not to stdout. At a terminal the lines are
  short and in colour, unless `NO_COLOR` is set. Each line has the date
  and the time to the millisecond, with its offset from UTC outside a
  terminal, and so does the log page.
- A user could disable itself and so lock out its own session and
  tokens. `PATCH /v1/users/{user_id}` now refuses that with `409`, as
  deleting oneself already was.
- `benethos-mailbox-service` requires fastapi 0.129.1, pydantic 2.12 and
  defusedxml 0.7.1 at least. With defusedxml 0.7.0, a broken autoconfig
  file ended discovery with an unhandled error. With an older fastapi,
  the served OpenAPI document differed from `docs/openapi.json`.
  pydantic 2.11 could not be installed beside the other minimums.
- The IMAP sync could miss a change in the folder its connection had
  selected last, e.g. a new mail in the inbox: the server answered STATUS
  for that folder from an older view. The sync now sends a NOOP first.
- A send the provider accepted answers with its result, even when the
  service cannot record the sent copy, the change or the audit entry
  afterwards. Before, such a failure answered `500`, stored nothing for
  the `Idempotency-Key`, and a retry with the same key sent the mail a
  second time.
- An unexpected error with one account or one webhook is logged and the
  sync worker and the webhook posts go on. Before, it ended both for the
  life of the process, while the API went on answering.
- A login the mail server refuses for now no longer blocks the account.
  IMAP answers with `[UNAVAILABLE]`, `[INUSE]`, `[LIMIT]` or
  `[SERVERBUG]`, or a text such as "too many connections", and SMTP
  answers with a 4xx code, now count as `502 provider_unavailable` and
  are tried again later. Before, they counted as a rejected credential
  and the account stayed blocked until it was verified.
- A user or role whose stored grant names a right that a release renamed
  stays manageable. Before, every change to it, its tokens and its
  password answered `400 unknown right`. New grants still refuse such a
  name.
- A user with `accounts.manage` or `admin` on named accounts can manage
  itself and hand out what it holds. Before, those groups name
  `create_account` and the like, which only a grant on `*` gives, so the
  user could not even rename itself.
- A mail from or to an address with an international domain is sent,
  with the domain in punycode in its headers and its Message-ID. Before,
  composing it answered `500`. An address whose local part goes beyond
  ASCII makes a message with UTF-8 headers, for servers with SMTPUTF8.
- `expires_at` of `POST /v1/users/{user_id}/tokens` needs a time zone,
  e.g. `2026-12-31T23:59:59Z`. Without one it answers `422`. Before, it
  answered `500`.
- The sends page of the UI lists the sends of deleted accounts too, for
  a user whose `audit` grant names every account, as
  `GET /v1/accounts/{account_id}/sends` does. Before, it listed existing
  accounts only.
- The names of users, tokens and roles are kept without the spaces
  around them, in the API as in the UI, and a user name has 200
  characters at most. Before, the API kept " Admin" with its space: it
  could not sign in, and "Admin" could be created beside it.
- A cursor of `GET /v1/messages` continues the search it came from and
  no other. With another `folder` or other search parameters it answers
  `400`. Before, it went on from its positions under the new parameters,
  and the folder of the new request was ignored. Cursors handed out
  before this version are refused once.
- An SMTP server that refuses an XOAUTH2 token counts as a rejected
  login, `502 provider_auth_failed`. Before, the service answered the
  server's challenge with the token again until smtplib gave up, and it
  counted as a failure of the server.
- A token made in the UI is valid for 1 day at least. Before, `0` made a
  token that had run out when it was shown.
- `port` and `smtp_port` in the settings of an IMAP account must be a
  whole number from 1 to 65535, else the account answers `400`. Before,
  a word answered `500`.
- `openapi` prints the document whatever key provider and OAuth app the
  settings name. Before, it failed when the key file or the client secret
  file was missing.
- A key provider whose content is no recovery key is named in the error,
  e.g. `the key file ... holds no recovery key`. Before, the error said
  only `not a recovery key`.
- The service refuses to start with a log level uvicorn does not know, a
  port outside 1 to 65535, or a longest webhook retry shorter than the
  first, and names the setting. Before, the log level ended in a
  traceback and the retry was capped quietly.
- `users` and `keys init` and `keys import` refuse to run with
  `MAILBOX_SERVICE_STORAGE=memory`, as `backup` did. Before, they
  reported success for a user or a data key that vanished with the
  command.
- A backup file that cannot be read or written, and a client secret file
  that is missing, are named in one line by the commands. Before, they
  ended with a traceback.
- A database of a newer schema, e.g. after a downgrade, is named in one
  line by every command. Before, each ended with a traceback.
- The database stores every time in UTC. A time with another offset was
  stored as given and compared wrongly with the others. The service
  itself always passed UTC.
- Sending from an IMAP account goes to the SMTP server while the IMAP
  server rests after it was unreachable. Before, the send was refused
  with "the mail server was unreachable".
- Verifying a Microsoft account asks Microsoft again for an access token
  when a refresh was refused before. Before, only a new sign-in or a
  restart of the service did.
- `has_attachments` means one thing in a list and in the message: a part
  a person sees as an attachment. An image the HTML shows in its place
  is none, a file marked inline, as Apple Mail sends a PDF, is one.
  Before, an opened HTML mail with inline images had attachments and the
  same mail in a list had none.
- `in_reply_to` of a message is one Message-ID, the first the header
  names. Before, a header the sender had folded came with its line break
  and every id in it.
- A top-level folder of a Microsoft account has `parent_id` null, as on
  IMAP. Before, it named the mailbox's root folder, which no list shows.
- `max_requests_per_minute` in the settings of an IMAP account must be a
  number above 0, else the account answers `400`. Before, a word or a
  negative number answered `500`.
- A message that another IMAP client removes while the service changes
  its flags is answered as not found, in `batch_messages` too. Before,
  it was missing from the answer.
- Moving a message whose Message-ID holds characters beyond ASCII on an
  IMAP server without COPYUID answers with the move. Before, the move
  went through and the request answered `500`.
- A search with text and `has_attachments=false` on a Microsoft account
  leaves out mail with attachments. Before, `false` was ignored there.
- On IMAP, a write the service tried again after the connection dropped
  answers with its result when the first try went through: a folder
  made, renamed or deleted, a message deleted. Before, it answered `409`
  or `404` for its own work.
- Replacing a draft that is gone answers `404` on IMAP accounts too, and
  stores nothing. Before, IMAP stored the new draft beside it and
  answered success, so a second draft appeared.
- Deleting a user removes its webhooks. Before, they stayed, posted
  nothing, and nobody could list or remove them. The database moves to
  schema 13, which drops those of users deleted before.
- `restore` refuses while the service runs on the database, as CONCEPT
  7.8 promised. A running service holds the lock file `mailbox.db.lock`
  beside its database. Before, on Linux the running service went on
  writing into the old file and the restore was lost at its next start,
  and on Windows the restore ended with a traceback.
- `restore` writes and migrates the backup beside the database first,
  then puts it in place in one step. Before, a crash in between left no
  database, and the next start created an empty one.
- `restore --recovery-key` no longer overwrites another master key the
  key provider holds, which the previous database needs. It refuses
  before restoring, and `--replace-master-key` overwrites it. The
  keyring provider now refuses to store over another key, as the file
  provider did.

### Security

- A valid API token passes while its client address is locked out for
  failed sign-ins, and clears no failures. Before, a lockout of an
  address refused every token behind it, so one client with a stale
  token stopped the others behind a proxy or NAT, and a working client
  reset the count of a guessing one.
- Renaming a user, or naming a new token of a user, is checked against
  the caller's rights on that user first. A caller who may not manage
  the user gets `403` and no longer learns from a `409` whether a name
  is taken.
- The access log writes the path of a request without its query, which
  held what a person typed, such as search terms.
- The service masks every secret it holds as `***` in its log and in
  error texts of the API, the UI and an account's last sync error:
  account passwords, OAuth tokens and client secret, webhook secrets.
  CONCEPT 7.4 promised this filter, but it was missing.
- IMAP reads have a limit. A message larger than 40 MB is refused with
  `502 provider_error`, as Microsoft accounts already did. In a list,
  headers beyond 256 KB are cut off.
- Discovery accepts only a host name as the domain. An address with a
  port, a path, invalid Punycode or whitespace answers `400 bad_request`.
  Before, a port or path went into the autoconfig URL, and invalid
  Punycode answered `500`.
- The check for public addresses takes an IPv6 address as public only
  inside `2000::/3`. Before, IPv4-compatible addresses such as `::a00:1`
  and site-local addresses passed. Webhook receivers are judged by the
  IPv4 address inside a NAT64 address.
- Every connection to an IMAP or SMTP server passes the host check again,
  and goes to the address it checked, with TLS verified against the host
  name. Before, the hosts of an account were checked only when it was
  created or changed, and each connection resolved the name anew. A host
  that now resolves to a non-public address answers `502 provider_error`.
  The IMAP probe of discovery connects to the address it just checked.
- A recipient pattern `*@domain` in a grant no longer accepts a local
  part with `%` or `!`, such as `bob%evil.org@domain`, which some servers
  route on to another host. Such an address needs its exact entry.
- An `Idempotency-Key` counts per account and user. Before, another user
  who sent the same key on the same account got `409
  idempotency_conflict`, e.g. a second MCP client sending the same mail.
  The database moves to schema 8, and the stored results of the last 24
  hours are dropped.
- The configuration UI keeps the message of a form in the session and
  shows it once. Before, it travelled in the URL as `?msg=` or `?err=`,
  and a link could put any text into the UI. The sign-in page takes only
  its own codes, `?notice=`. After an OAuth sign-in the provider's error
  text shows only for a sign-in the user started.
- `get_attachment` of the MCP server names the attachment's type outside
  the foreign-content marker only when it is a plain media type such as
  `image/png`. Any other value, which a sender may have chosen, counts as
  `application/octet-stream`.
- The MCP server sends its token over `http` only to this machine.
  `http` to another host needs `MAILBOX_SERVICE_ALLOW_HTTP=1`, else the
  server does not start. The compose file sets it for the network between
  the two containers.
- A Microsoft account takes its address from Graph `/me`, the mailbox's
  own address, no longer from the `email` claim of the ID token, which a
  tenant's administrators may set to anything. The sign-in asks for
  `User.Read` instead of `openid`, `email` and `profile`. Accounts
  connected before keep working. A new sign-in shows the new permission.
- A password beyond ASCII no longer leaks into an error. IMAP logs in
  with it by SASL PLAIN, where the server offers `AUTH=PLAIN`. SMTP and
  IMAP without it answer `400` that the login cannot carry it. Before,
  IMAP answered `500`, and SMTP answered `400` with a message that
  quoted one character of the password and its position.
- `get_attachment` of the MCP server hands an image to the model only up
  to 5 MB, larger ones by name. The PDF pages of one call share 12
  megapixels, so ten pages each come smaller than three. Before, an image
  of 10 MB and ten pages of 4 megapixels each went into one result.
- The MCP server no longer logs the URL of each request to the service
  at `INFO`. httpx wrote it, with search terms and message ids, into the
  log files of the MCP client.
- `keep_attachments` of `PUT /v1/accounts/{account_id}/drafts/{draft_id}`
  reads attachments of that draft alone. Before, a message id outside
  the drafts made the service fetch that message's attachment for a
  caller with the right to write drafts only, and the answer told
  whether the id existed.
- `PUT /v1/roles/{role_id}` needs the caller to cover every user who
  holds the role, as a change to those users would. Before, a delegated
  administrator could shrink a role that a stronger user held.
- An OAuth sign-in that comes back to another signed-in user answers as
  an unknown one and stays open for the user who started it. Before, it
  answered that someone else started it and ended it.
- A webhook may not post to the metadata services of AWS over IPv6
  (`fd00:ec2::254`) and of Alibaba Cloud (`100.100.100.200`). Their
  ranges stay open for receivers in a private network or a VPN.
- A request body larger than 40 MB is refused with `413
  payload_too_large`, in the API and in the UI, before the service reads
  it whole. Before, any size was read, and only a send checked the 25 MB
  of attachments afterwards.
- The grant editor of the UI takes 100 grants at most. Before, the row
  count came from the form unchecked, and a large one held up the
  service for minutes.
- A token revoked while a request with it was being checked stays
  revoked. Before, that request could save the token back as it had read
  it, and the revocation was lost.

## [0.1.0] - 2026-09-25

Pre-alpha. Not ready for production use: the API, the stored data and
the configuration may change without notice.

### Fixed

- `PATCH /v1/accounts/{account_id}/folders/{folder_id}` takes a role
  such as `archive` as the new `parent_id`, as creating a folder does.
- The start page of the configuration UI shows a right that covers only
  part of a group as that operation, as the user page does. Before, one
  operation showed as its whole group.
- `PATCH /v1/accounts/{account_id}` logs in to the provider only when
  the settings sent differ from the stored ones. Before, any `settings`
  in the body logged in, the same values included.
- A Microsoft account's keywords come back in lower case, as the other
  providers answer them. Renaming a top-level folder there no longer
  moves it. A move of a batch to several folders is refused per message,
  as on the other providers, not for the batch as a whole.
- A Microsoft account is left alone for as long as Graph's `Retry-After`
  asks, and a refresh token the provider refused is not sent again until
  the account is signed in anew.
- The next page of an IMAP folder asks the server for the older messages
  only, instead of reading every match and cutting the page here.
- A message of a Microsoft account deleted with `permanent=true`, and a
  draft there that is deleted or replaced, are gone for good. Before,
  one not in Deleted Items was only moved there, since that is what
  Graph's delete does outside the trash.
- A draft saved or a sent copy stored over a connection the IMAP server
  dropped right after the APPEND is stored once: the retry finds it by
  its Message-ID instead of storing it again.
- A connection dropped by the IMAP server during the login answers `502`
  (`provider_unavailable`) and is tried again on the next call. Before,
  it counted as a rejected credential and blocked the account until
  `verify`.
- Sending to an internationalised domain puts it in punycode on the SMTP
  envelope. An address with a local part beyond ASCII is sent with
  SMTPUTF8 where the server supports it, else refused with `400`. Before,
  both failed with `500`.
- Outgoing messages are composed 7bit clean: a body beyond ASCII is
  encoded, since the service asks no SMTP server for 8BITMIME.
- Keywords are set on an IMAP server that lists them in PERMANENTFLAGS or
  sends no PERMANENTFLAGS at all. Before, only `\*` counted, and such
  servers answered `501`.
- A credential encrypted with a key the service does not hold answers
  `500` (`credential_unreadable`) naming that key, instead of a failed
  decryption with the active one.
- Deleting an account forgets its `Idempotency-Key` results in the
  in-memory storage as well, as the database did.
- The sign-in page of the configuration UI leads back to the page that
  was asked for, with its query. After a posted form it leads to the
  start page. Before, it led to the path alone, and to a `405` after a
  form.
- A token's days valid on the configuration UI are bound to 3650. A
  larger number answered `500`.
- A reply's recipients are counted against the limit of 100 once they are
  taken from the original, not before.
- Cancelling an OAuth sign-in on the UI ends only a sign-in the caller
  started.
- Idle sessions of the configuration UI are swept at each sign-in.
- A missing attachment, draft or folder on an IMAP account answers `404`
  for that. Before, it was taken for a moved message: a sync ran and the
  answer said the message was not found.
- A list across accounts ends once every account still open has failed.
  An account that fails keeps its place while others deliver, as before,
  but no longer keeps the `next_cursor` alive forever with empty pages.
- The OAuth callback of a sign-in again needs the right that started it
  (`accounts.manage`), not the right to read the account.
- The configuration UI lists under a user's rights the limits of every
  grant that allows sending, `send_draft` included. Before, only `send`
  grants counted.
- Changing an account stores the new credentials before the record, so a
  failure between the two cannot leave settings without the credentials
  they need.
- The background watcher of an account ends as soon as the account is
  deleted, instead of logging a failure and waiting a minute first.
- `backup verify` without a file says how to use it. Before, it wrote a
  backup to a file named `verify`.
- `restore` moves a journal file left beside the old database along
  with it, so SQLite cannot roll it into the restored file.
- A truncated encrypted record, a key file that cannot be read and a
  credential store that does not answer are reported as what they are,
  instead of failing with a traceback.
- Autodiscovery keeps a mail server under an internationalised top-level
  domain such as `.рф`. Before, its punycode form was dropped as no host.
- A failure of the service's own database answers `500` with the code
  `storage_error` and the reason, a violated constraint `409`
  (`conflict`). Before, both were unhandled and the background sync
  stopped for good when an account was deleted during its sync.
- The MCP server's `--allowed-origins` without `--allowed-hosts` admits
  the hosts of those origins. Before, it answered every request with
  `421`, since no host was allowed.
- The MCP server tells the model what a `422` was about: the field and
  the reason, as `validation_error`. An answer that is not JSON is
  reported as `unexpected_response` instead of failing the tool.
- The MCP server reads an attachment only up to its limit of 10 MB and
  stops there. A PDF page is rendered within a budget of 4 million
  pixels, whatever size its MediaBox declares. An attachment with a
  charset Python does not know is read as UTF-8.
- The MCP server's bearer guard closes a websocket instead of passing it
  through unchecked.
- The MCP server quotes the ids a model hands it before they go into
  an API path.

### Security

- An `Idempotency-Key` belongs to the caller: the same key from another
  user answers `409` (`idempotency_conflict`) instead of the first
  caller's result.
- A source locked out after failed sign-ins stays locked out for its
  fifteen minutes. Before, a flood of failures from other addresses could
  push the lockout out of memory.
- A right on accounts that may not exist yet (`discover_account`,
  `create_account`, `start_oauth`) no longer makes every account visible:
  an account the caller has no other right on answers `404`, not `403`.
- The findings autodiscovery caches and the callers it counts are capped
  in memory.
- A NAT64 address (`64:ff9b::/96`) counts as public only when the IPv4
  address it carries is. Before, `64:ff9b::10.0.0.1` passed the check
  of autodiscovery and of an account's hosts as a public address.
- The MCP server puts the sender's words inside the `<mail-content>`
  marker in full: a message's date, from, to, cc, subject and attachment
  names as much as its body, and an attachment's filename. A list of
  messages carries a `note` that `from` and `subject` are the sender's.
  Before, only the body sat inside the marker.
- An HTML body cannot end a hidden element with an end tag of another
  name: `<div style="display:none">...</span> text</div>` kept `text`
  hidden in a mail client but the MCP server showed it. Now an end tag
  closes the innermost open element of its own name, and a stray one
  closes nothing.
- Listing the tokens of a user needs the rights that user holds, as
  creating and revoking them already did. Before, `users.manage` alone
  listed the token names and dates of any user, an admin's included.
- Guessed credentials are slowed down: a client address that fails to
  sign in ten times within fifteen minutes is locked out for fifteen
  minutes. On the API every request from it answers `429 rate_limited`
  with `Retry-After`, on the UI the sign-in page says so. A successful
  sign-in clears the count. Behind a reverse proxy, set
  `MAILBOX_SERVICE_FORWARDED_ALLOW_IPS` to the proxy's address, so the
  client address is read from `X-Forwarded-For`. Without it, every client
  behind the proxy counts as one.
- Every line break is refused in a header field of an outgoing message,
  not only CR and LF: `422` for a subject, a recipient name or an
  attachment name with a vertical tab, a form feed, NEL (U+0085) or a
  Unicode line or paragraph separator. A reply or a forward folds what the
  original carried in its subject or attachment names onto one line.
  Before, both answered `500`.
- The hosts in an account's settings (`host`, `smtp_host`) pass the same
  check as autodiscovery when the account is created or changed, before
  the first connection: a host that resolves to a private, loopback or
  link-local address is refused with `400`, unless it is listed in
  `MAILBOX_SERVICE_DISCOVERY_INTERNAL_HOSTS`. Before, anyone who could create
  or change an account could make the service connect into its own
  network. A host that does not resolve is refused with `400` as well.
- A request that fails validation (`422`) no longer comes back in the
  answer: `detail` carries `type`, `loc` and `msg` only, not FastAPI's
  `input` and `ctx`. Before, a wrong `POST /v1/accounts` returned the
  provider password it was sent, where proxies and client logs keep it.
- The database file is created readable by its owner alone (`0600`). An
  existing one that others may read is narrowed on start. On POSIX
  systems only.
- Search text with a line break or another control character is refused
  (`422`). Before, `q` could carry further IMAP commands into the
  account's session.

### Changed

- The MCP server's `--log-level` (and `MAILBOX_MCP_LOG_LEVEL`) takes
  `DEBUG`, `INFO`, `WARNING` or `ERROR`, in any case. Another value is
  refused at start instead of failing later.
- New API tokens are 64 characters after `mbx_` (were 43). Tokens made
  before stay valid.
- The service is now called `benethos-mailbox-service` (was
  `benethos-mailbox-api`). This covers the package, the command, the
  container image, the folders under `config/` and `data/`, and the entry
  of the master key in the OS credential store. Its settings start with
  `MAILBOX_SERVICE_` (was `MAILBOX_API_`). The MCP server reads
  `MAILBOX_SERVICE_URL` and `MAILBOX_SERVICE_TOKEN`.
- An account that has no credential of the kind its sign-in needs
  answers `409` (`credential_missing`). Before, it answered `500`
  (`credential_unreadable`), which stays for a credential that cannot be
  decrypted.
- A message without a recipient, one with more than 100 recipients or
  attachments over 25 MB is refused with `400` (`bad_request`) instead
  of `422`, on `send` and on the draft routes alike.
- A blank name for a user, a role or a token is refused with `400`, and
  so is a token `expires_at` that lies in the past.
- An IMAP account's `username` defaults to its address when left out, on
  create and when it is removed.
- The keywords `$seen`, `$flagged`, `$deleted` and `$recent` are refused
  with `422` on every provider: use `unread`, `starred` or a delete.
  Before, IMAP answered `400` and other providers stored them.
- A cursor that names no page answers `400` (`bad_request`) on every
  provider. Before, IMAP answered `404` and the memory provider failed.
- A missing drafts or trash folder answers `409` on every provider.
  Before, Microsoft answered `404`, and a batch delete failed as a whole.
- `folder_ids` with several folders answers `400` on every provider that
  keeps a message in one folder. Before, Microsoft moved to the first.
- Both packages ship the MIT license text.
- An account carries its `settings` (host, port, security, username,
  `smtp_*`), never a secret. Settings whose name looks like a secret
  (`password`, `secret`, `token`, `api_key`, ...) are refused with `400`:
  secrets go in `credentials`.
- Grants in responses carry `recipients` and `max_sends_per_day`, null
  where not set.
- `GET /v1/me` lists `accounts` as objects with `id`, `email`,
  `display_name` and `operations`, instead of a map from id to operations.
- New ids of accounts, users, tokens, keys and messages carry 64 random
  hex digits after their prefix (`acc_`, `usr_`, `tok_`, `key_`, `msg_`).
  Existing ids stay valid.
- Message ids of IMAP accounts are the service's own (`msg_…`) and stay the
  same when another client moves a message or the server renumbers a
  folder. Earlier ids are no longer accepted.
- Without `MAILBOX_SERVICE_KEY` and without any user, `/v1` answers
  `503 setup_required`.

### Added

- `PUT /v1/accounts/{account_id}/drafts/{draft_id}` takes
  `keep_attachments`, the ids of attachments of the stored draft that go
  into the new one. The MCP tool `update_draft` passes it on.
- Configuration UI: the grant editor shows the rights the MCP server uses
  (`mail.read`, `mail.write`, `drafts`, `send`) apart from the others. The
  tooltip of each group names the MCP tools it opens.
- Configuration UI: the user page shows the effective rights, the grants
  of the user and of its roles together. It lists them per account, with
  whole groups by name, the limits on sending and the warning where the
  user may read mail and send it anywhere. Only accounts the viewer can
  see are listed.
- MCP: every tool has a title and the hints read-only, destructive,
  idempotent and open world. `update_messages`, `update_draft` and
  `delete_draft` are idempotent. `list_accounts` is the only tool that
  stays inside the service.
- `folder_ids` of a message update and `parent_id` of a new folder take a
  role such as `archive` in place of a folder id, as `folder` of
  `list_messages` does.
- A token carries its `state`: `active`, `expired` or `revoked`.
- Each release publishes both packages to PyPI and both container images
  to `ghcr.io`, for `linux/amd64` and `linux/arm64`, under the same
  version.
- Accounts can connect by OAuth once the operator sets up an app for the
  provider (`MAILBOX_SERVICE_OAUTH_MICROSOFT_CLIENT_ID`, `_CLIENT_SECRET` or
  `_CLIENT_SECRET_FILE`, `_TENANT`). `POST /v1/oauth/{provider}/start`
  returns the provider's sign-in URL, to connect an account or, with
  `account_id`, sign it in again. The browser comes back to
  `/ui/oauth/{provider}/callback`. Only the refresh token is stored. The
  configuration UI offers "Sign in with Microsoft" when connecting and
  "Sign in again" on the account page. `MAILBOX_SERVICE_PUBLIC_URL` sets the
  address the redirect is built from.
- The `microsoft` adapter: Outlook.com and Microsoft 365 over Microsoft
  Graph, connected by OAuth. Folders, lists and search, messages,
  attachments, the source, flags, categories as keywords, moving,
  deleting, drafts and sending. Message ids stay the same when a message
  moves, search results included.
- A draft read with `get_message` carries its `reference`. A reference
  with `quote: false` keeps the link to the original without adding its
  quote, forwarded original or attachments again, so a draft can be
  replaced as a whole and stay in its thread. The configuration UI edits
  reply and forward drafts that way.
- Configuration UI under `/ui`. Not part of the OpenAPI document.
  - Sign in with an API token or the admin key. An overview of your
    accounts, rights and warnings.
  - Accounts: connect through autodiscovery or by hand, change, verify,
    remove.
  - Users, roles and their grants (with `recipients` and
    `max_sends_per_day`), tokens created (shown once) and revoked.
  - Mail: every inbox together, folders, search, a message as text,
    attachments and the original as downloads. Flags, moving and
    deleting, one message or the ticked ones. Folders created, renamed,
    moved and deleted. Writing, replying and forwarding with attachments,
    drafts saved, changed and sent, each send form with its own
    idempotency key.
  - The send audit of one account or of every account together.
- MCP server over streamable HTTP (`--transport streamable-http`, or
  `MAILBOX_MCP_*` in the environment), behind a bearer token
  (`MAILBOX_MCP_BEARER_TOKEN`, else `401`) and a Host/Origin check against
  DNS rebinding. Its container image `benethos-mailbox-mcp` is built with
  the service's and runs in compose with the profile `mcp`.
- Container image of the service (`containers/benethos-mailbox-service/`), for
  `linux/amd64` and `linux/arm64`, with a compose file that publishes the
  port on `127.0.0.1` only, and a GitHub workflow that pushes it to the
  GitHub container registry. See `containers/README.md`.
- `benethos-mailbox-service keys generate` prints a new master key for a key
  file or container secret and stores nothing.
- `GET /v1/me`: each account carries `warnings`, among them
  `read_and_send_anywhere` where the caller may read mail and send it to
  any address. The MCP
  server logs it at start.
- A mail or draft with `html` and without `text` gets a text part made
  from the HTML, without its hidden parts. Before, the text part was empty.
- MCP server: `send_message`, `create_draft` and `update_draft` take
  `html` besides `text`.
- Grants take `recipients` (addresses, `*@domain`, `*`) and
  `max_sends_per_day`, which narrow `send_message` and `send_draft`:
  `403 recipient_not_allowed`, `429 send_limit_reached` with
  `Retry-After`. A user with `users.manage` hands out sending only as
  narrow as its own.
- `GET /v1/accounts/{account_id}/sends`: every attempt to send, with user,
  token, recipients and outcome, never content. Right `list_sends`, group
  `audit`.
- MCP server: `list_folders`, `search_messages` and `get_message` besides
  `list_accounts`, which now says what may be done on each account. Only
  the tools the token's rights allow are offered. Mail content comes back
  as plain text inside `<mail-content>` markers, hidden HTML left out.
  stdio only for now.
- MCP server: `get_attachment` hands images over as images, PDF pages as
  PNG images, text types as text and other types by name, type and size.
- MCP server: `update_messages` marks read or unread, stars, moves (by
  folder id or role) and trashes up to 100 messages. `create_folder`
  creates a folder.
- MCP server: `list_drafts`, `create_draft`, `update_draft` and
  `delete_draft`. Drafts take plain text. A reply, reply to all or
  forward names its original with `original_id`.
- MCP server: `send_message` and `send_draft`, each with an
  `Idempotency-Key` derived from the call.
- Search filters on `GET /v1/accounts/{account_id}/messages` and
  `GET /v1/messages`: `from`, `to`, `subject`, `after`, `before` (days),
  `starred` and `has_attachments`, besides `q` and `unread`. `folder` on
  one account also takes a role such as `inbox`.
- `PATCH /v1/accounts/{account_id}/messages/{message_id}` sets `unread`,
  `starred` and `keywords` and answers the changed summary. Right:
  `update_message` (`mail.write`).
- `POST /v1/accounts/{account_id}/send` sends a message: `to`, `cc`,
  `bcc`, `reply_to`, `subject`, `text`, `html`, `attachments` (base64, 25 MB
  in all). The service sets From, Date and Message-ID and keeps a read
  copy in the sent folder. The answer names both and any refused
  recipients. Right: `send_message` (`send`). An account without an SMTP
  server answers `409`.
- `reference` on `POST .../send` replies to (`reply`, `reply_all`) or
  forwards (`forward`, with `forward_as` `inline` or `attachment`) a
  message of the account. The service sets the recipients of a reply,
  the subject prefix, In-Reply-To, References and the quote, and marks the
  original `$answered` or `$forwarded`. Needs `get_message` as well.
- Drafts: `GET`, `POST /v1/accounts/{account_id}/drafts`, `PUT` and
  `DELETE .../drafts/{draft_id}`. A draft takes the body of `send`,
  recipients optional, and is stored in the drafts folder. Its id is a
  message id and stays when the draft is replaced. Ids of other messages
  answer `404`. Right: `drafts`. A `reference` needs `get_message` as
  well.
- `POST /v1/accounts/{account_id}/drafts/{draft_id}/send` sends a draft as
  stored, dated now, then deletes it. A reply or forward marks its
  original. Takes `Idempotency-Key`. Right: `send_draft` (`send`).
- `Idempotency-Key` on `POST .../send`: the same key within 24 hours
  returns the first result instead of sending again. With a different
  message it answers `409 idempotency_conflict`.
- `PATCH /v1/accounts/{account_id}` changes the display name, settings
  (merged, `null` removes one) or credentials. New settings or credentials
  are tried first. Right: `update_account` (`accounts.manage`).
- IMAP accounts take an SMTP server for sending: `smtp_host`, `smtp_port`,
  `smtp_security` (`tls` or `starttls`), optionally `smtp_username`. The
  password is the IMAP one. Discovery fills them in, and creating or
  verifying an account logs in over SMTP too.
- `POST /v1/accounts/{account_id}/folders` creates a folder, subscribed,
  in the account's personal namespace. `PATCH .../folders/{folder_id}`
  renames or moves it, `DELETE` deletes it when it is empty and has no
  subfolders. Folders with a role answer `409`. Rights: `create_folder`,
  `update_folder` (`mail.write`), `delete_folder` (`mail.delete`).
- `POST /v1/accounts/{account_id}/messages/batch` applies one action,
  `update` with `changes` or `delete` with `permanent`, to up to 100
  messages and answers a result per id. Needs `batch_messages`
  (`mail.write`) and the right of the single operation.
- `DELETE /v1/accounts/{account_id}/messages/{message_id}` moves a message
  into the trash (`delete_message`, `mail.write`). `?permanent=true`
  deletes it for good and needs `delete_message_permanent` (`mail.delete`).
  `409` when there is no trash folder or the message is in it already.
- The same `PATCH` with `folder_ids` moves a message. Its id stays. An IMAP
  server needs `MOVE` or `UIDPLUS` for it, otherwise `501 not_supported`.
- Messages carry `keywords`, named as in JMAP: `$answered`, `$forwarded`,
  `$draft` and the provider's own.
- Folders carry `subscribed`: whether the folder is subscribed on the IMAP
  server, which decides whether mail clients such as Outlook show it.
  `null` where the provider has no subscriptions.
- A sync worker runs with `serve`: it watches the inbox of IMAP accounts
  over IDLE and polls the other folders, every 5 minutes by default
  (`MAILBOX_SERVICE_SYNC_INTERVAL`, `MAILBOX_SERVICE_SYNC_IDLE`). Accounts that need
  a new credential are left alone.
- `config/benethos-mailbox-service/.env.example` lists every setting of the
  service with its default. The service reads `.env` from that folder,
  relative to the working directory.
  `serve` names the database it uses.
- `POST /v1/discovery` with `{"email": ...}` returns ways to connect the
  address, best first: servers with port and encryption, the credential to
  ask for, hints, whether the answer is `confirmed`, and `settings` for
  `POST /v1/accounts`. Sources: built-in presets, the domain's autoconfig
  file, Thunderbird's ISPDB, the MX record. IMAP servers are asked for their
  capabilities without a login. `sources` reports what each source found.
  Right: `discover_account` (`accounts.manage`) on every account.
- `MAILBOX_SERVICE_DISCOVERY_ISPDB=false` switches ISPDB off,
  `MAILBOX_SERVICE_DISCOVERY_INTERNAL_HOSTS` (a JSON list) allows hosts with
  private addresses.
- `429 rate_limited` with `Retry-After`: more than 10 discoveries per minute
  by one user.
- Creating an account logs in first. Nothing is stored unless the provider
  accepts the credential: a rejected login answers `502
  provider_auth_failed`, a missing credential `400`.
- `POST /v1/accounts/{account_id}/verify` logs in afresh, clears a rejected
  login and updates the status. Right: `accounts.manage`.
- `GET /v1/messages` lists messages across accounts, newest first, with the
  same filters as one account plus `accounts` and a folder role. Accounts the
  caller may not read are left out. An account that fails is named in
  `incomplete` and keeps its place for the next page.
- Every message carries its `account_id`.
- IMAP special folders without SPECIAL-USE flags are recognised by their
  German or English name (Gesendet, Entwürfe, Papierkorb, Spam, Archiv, ...).
- Internationalised domains in addresses are returned in Unicode. A `Date`
  header without a zone is returned as UTC.
- IMAP accounts are paced by a rate limiter (setting
  `max_requests_per_minute`, default 60). A rejected login is not retried
  until the credential changes. Timeouts and dropped connections are retried
  with backoff, then the server is left alone for a pause that grows from 30
  seconds up to 15 minutes. The client identifies itself with IMAP `ID`.
- Account status `unreachable`. The status follows the provider: a rejected
  login sets `needs_reauth`, an unreachable server `unreachable`, success
  `connected`. Errors of an unreachable server carry the code
  `provider_unavailable`.
- IMAP accounts (`provider: imap`), read-only: folders with their roles,
  messages newest first with cursor paging, unread and text filters, single
  messages with text, HTML and attachments. Settings `host`, `username`,
  `port`, `security` (`tls` or `starttls`) and `auth` (`password` or
  `xoauth2`), credential `password` or `access_token`. Reading never marks a
  message as read.
- `GET .../messages/{message_id}/raw` returns the RFC 822 source,
  `GET .../messages/{message_id}/attachments/{attachment_id}` an attachment.
- `benethos-mailbox-service backup FILE`, `backup verify FILE` and
  `restore FILE`: encrypted backups of the whole database, opened with the
  master key or, with `--recovery-key`, the recovery key.
- Accounts take `credentials` on creation. They are stored encrypted and
  never returned. An account lists only which credentials it has.
- `benethos-mailbox-service keys init` creates the keys and prints the recovery
  key once, `keys import` stores the master key from a recovery key.
- Master key providers: the OS credential store (default), a key file, or
  `MAILBOX_SERVICE_MASTER_KEY`.
- Accounts, users, roles and tokens are stored in SQLite in
  `data/benethos-mailbox-service/`, relative to the working directory. `MAILBOX_SERVICE_DATA_DIR` moves it,
  `MAILBOX_SERVICE_STORAGE=memory` keeps nothing.
- `benethos-mailbox-service users create-admin` creates a user with every right
  and prints its token once.
- Users with roles and grants per account and per operation:
  `/v1/users`, `/v1/roles`.
- API tokens per user: `/v1/users/{user_id}/tokens`. A token is shown once on
  creation and can expire and be revoked.
- `/v1/me` returns the caller and its effective rights, `/v1/permissions`
  the catalogue of rights and groups.
- A caller can only grant rights it holds, and only manage users whose rights
  it holds.
- Rights are checked on every `/v1` request, per account and per operation.
  An account without a grant answers `404`, a missing right `403 forbidden`.
  `list_accounts` returns only the accounts the caller may read.
- Every `/v1` operation carries its required right as `x-permission` in the
  OpenAPI document.
- Two distributions in one uv workspace: `benethos-mailbox-service` (the service)
  and `benethos-mailbox-mcp` (the MCP server, a REST client only).
- MCP server skeleton over stdio or streamable HTTP with a first tool,
  `list_accounts`. Configured by `MAILBOX_SERVICE_URL` and `MAILBOX_SERVICE_TOKEN`.
- REST skeleton on FastAPI: `/health`, account CRUD, folder list, message list
  with cursor pagination and filters, single message.
- Bearer authentication on every `/v1` route.
- In-memory provider for tests and local development.
- OpenAPI 3.1 document with stable `operationId`s, the `bearerAuth` scheme
  and documented error responses. `benethos-mailbox-service openapi` prints it,
  and `docs/openapi.json` holds the current version.
- One error envelope `{"error": {"code", "message"}}`, authentication errors
  included.

[Unreleased]: https://github.com/benethos-hub/mailbox/compare/v0.2.0...HEAD
[0.2.0]: https://github.com/benethos-hub/mailbox/compare/v0.1.0...v0.2.0
[0.1.0]: https://github.com/benethos-hub/mailbox/releases/tag/v0.1.0
