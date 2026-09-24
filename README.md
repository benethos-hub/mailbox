# Mailbox API

One REST API for all your mailboxes, whichever provider they are at, with
an MCP server on top so an AI assistant can work with them too.

> **Status: 0.1.0, pre-alpha.** IMAP accounts with autodiscovery from the
> address: reading (folders, messages, search, attachments, raw source,
> across accounts), stable message ids kept by a background sync, changing
> and moving messages, folders, drafts, and sending over SMTP with reply,
> forward and `Idempotency-Key`. The MCP server's tools are next. What
> comes next and in which order:
> [docs/ROADMAP.md](docs/ROADMAP.md). The design behind it:
> [docs/CONCEPT.md](docs/CONCEPT.md).

## What it is

Most people and small companies have several mail accounts: a personal
GMX or web.de address, a company mailbox at Microsoft 365, a Gmail account,
an info@ address at some hoster. Each speaks its own dialect, IMAP here,
Microsoft Graph there, the Gmail API elsewhere.

**Mailbox API** puts one service in front of all of them:

- **one API** for reading, searching, sorting and sending mail, the same for
  every provider (OpenAPI 3.1)
- **many accounts** connected once, credentials stored encrypted
- **its own users and rights**: every caller gets exactly the accounts and
  operations it needs, for example "read account A, write drafts in account
  B, never send"
- **running in the background**, so it notices new mail while no client is
  open

On top of it, **Mailbox MCP** makes the same mailboxes available to AI
assistants such as Claude, limited to what its user may do.

## Name

| | |
|---|---|
| Project | Mailbox API |
| Service | `benethos-mailbox-api` |
| MCP server | `benethos-mailbox-mcp` |
| Environment prefix | `MAILBOX_API_` |

## Use cases

- **An assistant for your inbox.** "What came in today across all my
  accounts?", "Summarize the thread with the tax advisor", "Draft a reply
  to the landlord" - via the MCP server, with drafts only if you want a
  person to press send.
- **One inbox for tools.** A dashboard, a CRM or a script reads and files
  mail from every account through one interface instead of three.
- **Automation.** Sort invoices into a folder, forward order confirmations,
  archive newsletters, triggered by new-mail events.
- **Controlled access.** A bookkeeping tool may read the invoice folder of
  one account and nothing else. A newsletter job may send from info@ and do
  nothing else.
- **Self-hosted.** Runs on your own machine or server. Credentials and mail
  never pass through a third-party cloud.

## Supported providers (planned)

| Provider | Connected via | Credential |
|---|---|---|
| Gmail / Google Workspace | Gmail API | OAuth, with your own Google Cloud client |
| Microsoft 365, Outlook.com | Microsoft Graph | OAuth |
| Fastmail, Stalwart, other JMAP servers | JMAP | API token |
| GMX, web.de, T-Online, Yahoo, AOL, iCloud, Posteo, mailbox.org, IONOS, Strato, own mail servers | IMAP + SMTP | app password |
| Proton Mail | IMAP + SMTP through Proton Mail Bridge | Bridge password |
| legacy mailboxes | POP3, reduced functionality | password |

Not supportable: Tuta, which offers no IMAP and no API. Details per provider
in [docs/CONCEPT.md](docs/CONCEPT.md), section 5.3.

## Parts

| Package | What it is | Runs |
|---|---|---|
| [`benethos-mailbox-api`](packages/mailbox-api) | the service: REST API, users and rights, mail accounts, encrypted credentials, provider adapters, background fetching | permanently |
| [`benethos-mailbox-mcp`](packages/mailbox-mcp) | the MCP server, a client of the REST API only | per client over stdio, or over HTTP |

```
 AI assistant ──MCP──► benethos-mailbox-mcp ──┐
 scripts, apps ───────────────────────────────┼─REST──► benethos-mailbox-api ──► IMAP / Gmail / Graph
```

One uv workspace, one lockfile, two distributions.

## Development

```
uv sync
uv run pytest -q
uv run ruff check . && uv run ruff format --check .
uv run mypy
```

Live checks against test accounts, outside the test suite:
`uv run python live/smoke.py` reads only, `uv run python live/changes.py`
sends one test mail between two test accounts, moves it and deletes it.
Both are configured in `live/.env` (template `live/.env.example`).

## Running

```
uv run benethos-mailbox-api keys init              # once: prints the recovery key
uv run benethos-mailbox-api users create-admin     # once: prints an admin token
uv run benethos-mailbox-api serve
MAILBOX_API_TOKEN=<token> uv run benethos-mailbox-mcp
```

The API documentation is at `http://127.0.0.1:8080/docs`. Data is kept in a
SQLite database in `data/benethos-mailbox-api/`. Settings come from the
environment or from `config/benethos-mailbox-api/.env`; copy the
`.env.example` beside it to start. Both paths count from the working
directory, normally the repository root.

| Setting | Meaning |
|---|---|
| `MAILBOX_API_KEY` | optional built-in admin key, for containers and tests |
| `MAILBOX_API_DATA_DIR` | where the database lives, default `data/benethos-mailbox-api` in the working directory |
| `MAILBOX_API_STORAGE` | `sqlite` (default) or `memory`, which keeps nothing |
| `MAILBOX_API_HOST`, `MAILBOX_API_PORT` | where the API listens, default `127.0.0.1:8080` |
| `MAILBOX_API_KEY_PROVIDER` | where the master key lives: `keyring` (default), `file` or `env` |
| `MAILBOX_API_KEY_FILE` | the key file, for `file` |
| `MAILBOX_API_MASTER_KEY` | the recovery key, for `env` |
| `MAILBOX_API_DISCOVERY_ISPDB` | `true` (default) or `false`: whether autodiscovery asks Thunderbird's ISPDB |
| `MAILBOX_API_DISCOVERY_INTERNAL_HOSTS` | JSON list of hosts autodiscovery may reach on private addresses |
| `MAILBOX_API_SYNC_INTERVAL` | seconds between two polls of every folder by the sync worker, default `300`, `0` switches it off |
| `MAILBOX_API_SYNC_IDLE` | `true` (default) or `false`: whether the sync worker watches the inbox over IMAP IDLE, with a second connection per account |

Mail credentials are stored encrypted (AES-256-GCM). The master key stays
out of the database, in the key provider. `keys init` prints a recovery key
once: keep it apart from backups. `keys import` reads it back into the key
provider, for example on a new machine.

### Backup and restore

```
uv run benethos-mailbox-api backup mailbox.bak          # while the service runs
uv run benethos-mailbox-api backup verify mailbox.bak
uv run benethos-mailbox-api restore mailbox.bak         # service stopped
uv run benethos-mailbox-api restore mailbox.bak --recovery-key   # on a new machine
```

A backup holds accounts, users, rights, token hashes and the encrypted
credentials, never mail. The whole file is encrypted, and it opens only with
the master key or the recovery key, which are not in it. `restore` keeps the
previous database beside the restored one.

### Authentication

**Every route under `/v1` requires authentication.** Nothing is served
anonymously, only `/health` is open. How a caller authenticates is a
separate question from what it may do:

- **Who is calling** is proven by a credential of a user of the service.
  The first kind is an API token, sent as `Authorization: Bearer <token>`.
  Further kinds are planned without changing the rights model: password
  with TOTP or a passkey for the configuration UI, OAuth 2.0 client
  credentials for machines.
- **What the caller may do** follows from the user's rights, per account and
  per API operation, checked on every request. `GET /v1/me` shows them.

Users, roles and tokens are managed under `/v1/users` and `/v1/roles`. A
token is shown once, when it is created. With neither a user nor
`MAILBOX_API_KEY`, the API answers `503 setup_required`.

See [docs/CONCEPT.md](docs/CONCEPT.md), section 7.5.

## Licence

MIT
