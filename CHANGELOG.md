# Changelog

All notable changes to this project are documented here. The format follows
[Keep a Changelog](https://keepachangelog.com/en/1.1.0/), and the project
adheres to [Semantic Versioning](https://semver.org/).

## [Unreleased]

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

[Unreleased]: https://github.com/benethos-hub/mailbox/compare/v0.1.0...HEAD
[0.1.0]: https://github.com/benethos-hub/mailbox/releases/tag/v0.1.0
