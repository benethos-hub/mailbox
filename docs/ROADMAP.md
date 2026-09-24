# Roadmap

The phases in which Mailbox API is built. What each item means is designed
in [CONCEPT.md](CONCEPT.md). The section numbers below point there.

| Phase | Topic | State |
|---|---|---|
| [0](#phase-0--skeleton) | Skeleton | **done** |
| [1a](#phase-1a--users-rights-storage-backup) | Users, rights, storage, backup | **done** |
| [1b](#phase-1b--imap-reading-and-autodiscovery) | IMAP reading and autodiscovery | **done** |
| [1c](#phase-1c--stable-ids-and-sync-worker) | Stable ids and sync worker | **done** |
| [2](#phase-2--writing-and-sending) | Writing and sending | **done** |
| [3](#phase-3--mcp-server-and-container) | MCP server and container | in progress |
| [4](#phase-4--change-feed-and-webhooks) | Change feed and webhooks | |
| [5](#phase-5--more-providers-and-the-configuration-ui) | More providers and the configuration UI | |

Undecided ideas wait in [IDEAS.md](IDEAS.md) until they are designed.

The MCP server comes before Gmail and Microsoft on purpose: with IMAP it
already covers most providers through app passwords, and it proves the API
design early.

## Phase 0 – Skeleton

**Done.**

- uv workspace with two distributions: service and MCP server
- CI, ruff, mypy, pytest with an 80 % coverage floor
- FastAPI app in three layers (`web` → `domain` → `data`, 1.1), checked by
  an architecture test
- Bearer authentication with one static admin key, one error envelope
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
  source. Password, app password and XOAUTH2. One shared connection per
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

- **MCP read tools over stdio, registered by the token's rights (8)**, done
- **MCP write tools `update_messages` and `create_folder` (8)**, done
- **The MCP server registers only what its user may do (`/v1/me`)**, done
- **MCP draft tools `list_drafts`, `create_draft`, `update_draft`,
  `delete_draft` (8)**, done
- **MCP send tools `send_message` and `send_draft` (8)**, done
- Prompt injection measures (7.7): mail content marked as foreign and
  hidden HTML dropped (done); the read-and-send warning, send audit
- Grant constraints `recipients` and `max_sends_per_day` (7.5), together
  with the send tools
- Policy file, nothing enabled by default
- Bearer guard for the MCP server's HTTP transport
- Container image and compose file for the service, bound to the loopback
  address (8.1)

## Phase 4 – Change feed and webhooks

- Change feed, `/v1/changes`, and the MCP tool `whats_new` (6.5)
- Webhooks

## Phase 5 – More providers and the configuration UI

- `microsoft` adapter over Graph with OAuth (5.4)
- `gmail` adapter with OAuth, own Google Cloud client per deployment (5.5)
- Gmail history and Graph delta in the worker
- `jmap` adapter for Fastmail and JMAP servers (5.6)
- Configuration UI under `/ui` (1.1): accounts, OAuth, users, tokens,
  recovery key, status
- Threads (6.3): for IMAP built across folders from the id mapping,
  which then also keeps `In-Reply-To` and `References`
- Grant constraint `folders` (7.5)
- `pop3` adapter (5.2)

## Keeping this file current

Change the state column when a phase starts or ends, and tick a phase off
in the same commit that finishes it. A new item goes into the phase it
belongs to, with the CONCEPT section that designs it. An item without a
design goes into CONCEPT.md first.
