# Roadmap: phases 0 to 4c

Part of the [roadmap](../ROADMAP.md): the phases that are done.

## Phase 0 – Skeleton

**Done.**

- uv workspace with two distributions: service and MCP server (four
  since 0.4.0, five since 0.11.0, CONCEPT 9)
- CI, ruff, mypy, pytest with an 80 % coverage floor
- FastAPI app in three layers (`web` → `domain` → `data`, 1.1), checked by
  an architecture test
- Bearer authentication, one error envelope
- OpenAPI 3.1 export with stable `operationId`s and contract tests (6.8)
- Accounts, folders and messages as read routes on the in-memory adapter
- MCP server skeleton over stdio and streamable HTTP with `list_accounts`

## Phase 1a – Users, rights, storage, backup

**Done.**

Everything real mail will depend on, before any real mailbox is connected.

- **Users and rights (7.5):** users with roles and grants per account and
  per operation, API tokens as their first credential, `/v1/me`,
  `/v1/users`, `/v1/roles`, `x-permission` on every route, rights checked
  in the domain
- **Storage:** SQLite for accounts and users, behind the repository
  protocols
- **Credentials (7.3):** envelope encryption, key providers (keyring, file,
  env), recovery key
- **Backup and restore (7.8):** `backup`, `restore`, `backup verify`, the
  whole file encrypted

## Phase 1b – IMAP reading and autodiscovery

**Done.**

- **`imap` adapter (5.1):** folders, list, search, get, attachments, raw
  source. Password and app password. XOAUTH2 on the wire, refused for
  accounts until a token refresher exists (5.1). One shared connection per
  account
- **Being a good client (5.9):** rate limiter per account, no retry of a
  failed login, backoff, `IMAP ID`
- **Encodings (5.10):** modified UTF-7, localised special folders, broken
  charsets, IDN, with fixtures
- **Across accounts (6.6):** `GET /v1/messages`, merged, partial results
- **Autodiscovery (5.8):** presets, autoconfig, ISPDB, MX, with all
  security rules
- `verify` before a credential is stored
- Live checks against test accounts on our own IMAP server

## Phase 1c – Stable ids and sync worker

**Done.** Before phase 2, so that ids stay valid once messages are moved.

- **Id mapping (4.1):** our own message ids for IMAP, kept in the store
- **Sync worker (8.1):** IDLE on the inbox, the other folders polled,
  moves by other clients recognised by `Message-ID`
- A lookup that misses syncs the account and tries again
- Live checks: IDLE, and an id that survives a move by another client

## Phase 2 – Writing and sending

**Done.**

- **IMAP protocol on IMAPClient (5.1)**, done
- **SMTP through the standard library's `smtplib` (5)**, done
- **`COPYUID` keeps the id of a message we move (4.1)**, done
- **Update, delete and batch operations on messages (6.3)**, done
- **Folder create, rename, delete (6.2)**, done
- **Sending over SMTP, with reply and forward by reference, `forward_as`,
  `\Answered` and `$Forwarded` on the original (6.4)**, done
- **Drafts: list, create, replace, delete, send (6.4)**, done
- **`Idempotency-Key` on send (6.4)**, done
- **Search filters `from`, `to`, `subject`, `after`, `before`, `starred`,
  `has_attachments`, folder by role (6.6)**, done

## Phase 3 – MCP server and container

**Done.**

- **MCP read tools over stdio, registered by the token's rights (8)**, done
- **MCP write tools `update_messages` and `create_folder` (8)**, done
- **The MCP server registers only what its user may do (`/v1/me`)**, done
- **MCP draft tools `list_drafts`, `create_draft`, `update_draft`,
  `delete_draft` (8)**, done
- **MCP send tools `send_message` and `send_draft` (8)**, done
- **Grant constraints `recipients` and `max_sends_per_day` (7.5), with the
  audit of sends (`GET {acc}/sends`)**, done
- **Prompt injection measures (7.7): mail content marked as foreign, hidden
  HTML dropped, send audit, the read-and-send warning in `/v1/me` and the
  MCP start log**, done
- **The MCP server over streamable HTTP, behind a bearer guard, with its
  own container image**, done
- **Container image and compose file for the service, bound to the loopback
  address (8.1)**, done: `containers/`. Both images are built by the CI
  and published for amd64 and arm64 with each release (decided
  2026-09-25).

## Phase 4 – Change feed and webhooks

**Done.**

- **The change log: every sync pass and every change through the API
  records created, updated and deleted messages, kept for
  `MAILBOX_SERVICE_CHANGES_DAYS` days (6.5)**, done
- **`GET {acc}/changes` and `GET /v1/changes` with an opaque state (6.5)**,
  done: paged with `more`, `410 changes_expired` for a state the feed no
  longer knows, live-checked in `live/mailbox-service/changes.py`
- **The MCP tool `whats_new` (8)**, done, live-checked in `live/mailbox-mcp/mcp_stdio.py`
- **IMAP: CONDSTORE where the server offers it, so flag changes from other
  clients reach the feed (6.5)**, done, live-checked
- **Microsoft: Graph delta queries in the worker, so the feed covers
  Microsoft accounts (5.4, 6.5)**, done, live-checked in `live/mailbox-service/microsoft.py`
- **Webhooks: register, sign with HMAC-SHA256, deliver with retries
  (6.5)**, done, live-checked in `live/mailbox-service/changes.py` against a receiver at
  127.0.0.1. Their pages in the UI came with phase 4b.
- decided 2026-09-25: IMAP and Microsoft in this phase, CONDSTORE, 7 days
  by default (CONCEPT 6.5)

## Phase 4a – Password sign-in

**Done.**

- **Passwords as a credential kind of a user: scrypt, unique names,
  NIST rules, the same answer for a wrong name (7.5)**, done
- **The UI signs in with name and password, the session holds the user,
  a changed password ends the other sessions (1, 7.5)**, done,
  live-checked in `live/mailbox-service/ui.py`
- **Change the own password, set another user's within one's rights,
  change at the next sign-in after that (7.5)**, done, live-checked
- **`users create-admin` with a one-time password, `users set-password`
  on the host (7.5)**, done: every live check with a service of its own
  starts that way
- **Every caller is a user: tests and live checks use a user and a
  token (7.5)**, done
- **Sign-ins in the service log, a brake per user name (1, 7.5)**, done
- decided 2026-09-27: the UI takes passwords only, tokens are for the API
  and MCP, every caller a user, a one-time password for the first admin, a
  second factor later (built in phase 5, AUTHENTICATION.md)

## Phase 4b – UI rework

**Done.**

A rework of the configuration UI before the providers of phase 5.
Scope, page types and the rules for every page in [UI.md](../mailbox-service/UI.md).

- **The frame: palette, sidebar, top bar with breadcrumb, components
  (UI 3, 7)**, done
- **The overview: you, your accounts, the service (UI 5)**, done: the
  last sign-in stored (schema 10), the sync state in memory
- **Accounts and connecting from the address (UI 6.1)**, done
- **Users, roles and tokens in the page types (UI 6.3)**, done
- **Mail and sends in the page types, the filter bar with chips (UI 4.4,
  4.5)**, done
- **Webhooks with a delivery log (UI 6.4)**, done: the last 20 posts of
  each (schema 11)
- **Status and the recovery key (UI 6.5)**, done
- **Paging and filters on every list (UI 4.5, 4.6)**, done
- all live-checked in `live/mailbox-service/ui.py`
- decided 2026-09-27: UI.md as written, the recovery key for `admin`
  after the password, the sync state in memory, a delivery log, no
  Changes page yet (UI 10)

## Phase 4c – API users

**Done.**

- **The UI sign-in switch `ui_sign_in` on the user: off for new users,
  in the API and the UI, the password deleted when it goes off
  (CONCEPT 7.5, UI 6.3)**, done: schema 12, live-checked in
  `live/mailbox-service/ui.py`
- **Nobody disables itself or takes its own UI sign-in (7.5)**, done
- decided 2026-09-27: a switch rather than a password removed by hand,
  new users are API users by default
