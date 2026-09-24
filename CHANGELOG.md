# Changelog

All notable changes to this project are documented here. The format follows
[Keep a Changelog](https://keepachangelog.com/en/1.1.0/), and the project
adheres to [Semantic Versioning](https://semver.org/).

## [Unreleased]

### Security

- Search text with a line break or another control character is refused
  (`422`). Before, `q` could carry further IMAP commands into the
  account's session.

### Changed

- `GET /v1/me` lists `accounts` as objects with `id`, `email`,
  `display_name` and `operations`, instead of a map from id to operations.
- New ids of accounts, users, tokens, keys and messages carry 64 random
  hex digits after their prefix (`acc_`, `usr_`, `tok_`, `key_`, `msg_`).
  Existing ids stay valid.
- Message ids of IMAP accounts are the service's own (`msg_…`) and stay the
  same when another client moves a message or the server renumbers a
  folder. Earlier ids are no longer accepted.
- Without `MAILBOX_API_KEY` and without any user, `/v1` answers
  `503 setup_required`.

### Added

- MCP server: `list_folders`, `search_messages` and `get_message` besides
  `list_accounts`, which now says what may be done on each account. Only
  the tools the token's rights allow are offered. Mail content comes back
  as plain text inside `<mail-content>` markers, hidden HTML left out.
  stdio only for now.
- MCP server: `get_attachment` hands images over as images, PDF pages as
  PNG images, text types as text and other types by name, type and size.
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
  copy in the sent folder; the answer names both and any refused
  recipients. Right: `send_message` (`send`). An account without an SMTP
  server answers `409`.
- `reference` on `POST .../send` replies to (`reply`, `reply_all`) or
  forwards (`forward`, with `forward_as` `inline` or `attachment`) a
  message of the account. The service sets the recipients of a reply,
  the subject prefix, In-Reply-To, References and the quote, and marks the
  original `$answered` or `$forwarded`. Needs `get_message` as well.
- Drafts: `GET`, `POST /v1/accounts/{account_id}/drafts`, `PUT` and
  `DELETE .../drafts/{draft_id}`. A draft takes the body of `send`,
  recipients optional, and is stored in the drafts folder; its id is a
  message id and stays when the draft is replaced. Ids of other messages
  answer `404`. Right: `drafts`; a `reference` needs `get_message` as well.
- `POST /v1/accounts/{account_id}/drafts/{draft_id}/send` sends a draft as
  stored, dated now, then deletes it; a reply or forward marks its
  original. Takes `Idempotency-Key`. Right: `send_draft` (`send`).
- `Idempotency-Key` on `POST .../send`: the same key within 24 hours
  returns the first result instead of sending again; with a different
  message it answers `409 idempotency_conflict`.
- `PATCH /v1/accounts/{account_id}` changes the display name, settings
  (merged, `null` removes one) or credentials. New settings or credentials
  are tried first. Right: `update_account` (`accounts.manage`).
- IMAP accounts take an SMTP server for sending: `smtp_host`, `smtp_port`,
  `smtp_security` (`tls` or `starttls`), optionally `smtp_username`; the
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
  (`MAILBOX_API_SYNC_INTERVAL`, `MAILBOX_API_SYNC_IDLE`). Accounts that need
  a new credential are left alone.
- `config/benethos-mailbox-api/.env.example` lists every setting of the
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
- `MAILBOX_API_DISCOVERY_ISPDB=false` switches ISPDB off,
  `MAILBOX_API_DISCOVERY_INTERNAL_HOSTS` (a JSON list) allows hosts with
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
- `benethos-mailbox-api backup FILE`, `backup verify FILE` and
  `restore FILE`: encrypted backups of the whole database, opened with the
  master key or, with `--recovery-key`, the recovery key.
- Accounts take `credentials` on creation. They are stored encrypted and
  never returned; an account lists only which credentials it has.
- `benethos-mailbox-api keys init` creates the keys and prints the recovery
  key once, `keys import` stores the master key from a recovery key.
- Master key providers: the OS credential store (default), a key file, or
  `MAILBOX_API_MASTER_KEY`.
- Accounts, users, roles and tokens are stored in SQLite in
  `data/benethos-mailbox-api/`, relative to the working directory. `MAILBOX_API_DATA_DIR` moves it,
  `MAILBOX_API_STORAGE=memory` keeps nothing.
- `benethos-mailbox-api users create-admin` creates a user with every right
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
- Two distributions in one uv workspace: `benethos-mailbox-api` (the service)
  and `benethos-mailbox-mcp` (the MCP server, a REST client only).
- MCP server skeleton over stdio or streamable HTTP with a first tool,
  `list_accounts`. Configured by `MAILBOX_API_URL` and `MAILBOX_API_TOKEN`.
- REST skeleton on FastAPI: `/health`, account CRUD, folder list, message list
  with cursor pagination and filters, single message.
- Bearer authentication on every `/v1` route.
- In-memory provider for tests and local development.
- OpenAPI 3.1 document with stable `operationId`s, the `bearerAuth` scheme
  and documented error responses. `benethos-mailbox-api openapi` prints it,
  and `docs/openapi.json` holds the current version.
- One error envelope `{"error": {"code", "message"}}`, authentication errors
  included.
