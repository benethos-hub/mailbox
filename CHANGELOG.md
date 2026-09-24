# Changelog

All notable changes to this project are documented here. The format follows
[Keep a Changelog](https://keepachangelog.com/en/1.1.0/), and the project
adheres to [Semantic Versioning](https://semver.org/).

## [Unreleased]

### Changed

- Message ids of IMAP accounts are the service's own (`msg_…`) and stay the
  same when another client moves a message or the server renumbers a
  folder. Earlier ids are no longer accepted.
- Without `MAILBOX_API_KEY` and without any user, `/v1` answers
  `503 setup_required`.

### Added

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
