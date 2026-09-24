# Mailbox API

One REST API for all your mailboxes, whichever provider they are at, with
an MCP server on top so an AI assistant can work with them too.

> **Status: 0.1.0, pre-alpha.** The REST skeleton runs against an in-memory
> provider. What comes next and in which order:
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

## Running

```
MAILBOX_API_KEY=change-me uv run benethos-mailbox-api serve
MAILBOX_API_TOKEN=change-me uv run benethos-mailbox-mcp
```

The API documentation is at `http://127.0.0.1:8080/docs`.

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
  per API operation, checked on every request.

See [docs/CONCEPT.md](docs/CONCEPT.md), section 7.5.

**Current state (pre-alpha, temporary):** users do not exist yet. The only
credential is one static admin key, `MAILBOX_API_KEY`, sent as bearer
token, and whoever presents it may do everything. There is no default:
`change-me` above is a placeholder, and without a key set the API refuses
every request. The MCP server uses the same key as `MAILBOX_API_TOKEN`, and
so has full rights for now. Once users exist, the admin key is only for
setting things up, and the MCP server gets a user of its own with only the
rights it needs.

## Licence

MIT
