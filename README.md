# Mailbox Service

[![CI](https://github.com/benethos-hub/mailbox/actions/workflows/ci.yml/badge.svg)](https://github.com/benethos-hub/mailbox/actions/workflows/ci.yml)
[![PyPI api](https://img.shields.io/pypi/v/benethos-mailbox-service?label=PyPI%20api)](https://pypi.org/project/benethos-mailbox-service/)
[![PyPI mcp](https://img.shields.io/pypi/v/benethos-mailbox-mcp?label=PyPI%20mcp)](https://pypi.org/project/benethos-mailbox-mcp/)
[![Container](https://img.shields.io/badge/ghcr.io-mailbox--api-2496ED?logo=docker&logoColor=white)](https://github.com/benethos-hub/mailbox/pkgs/container/benethos-mailbox-service)
[![Container](https://img.shields.io/badge/ghcr.io-mailbox--mcp-2496ED?logo=docker&logoColor=white)](https://github.com/benethos-hub/mailbox/pkgs/container/benethos-mailbox-mcp)
[![Python](https://img.shields.io/pypi/pyversions/benethos-mailbox-service)](https://pypi.org/project/benethos-mailbox-service/)
[![Coverage](https://img.shields.io/badge/coverage-96%25-brightgreen)](https://github.com/benethos-hub/mailbox/actions/workflows/ci.yml)
[![License](https://img.shields.io/badge/license-MIT-blue)](https://github.com/benethos-hub/mailbox/blob/main/LICENSE)

One REST API for all your mailboxes, whichever provider they are at, and
an MCP server on top. Scripts, tools and AI assistants work with your
mail through one door you control.

> **Status: pre-alpha, version 0.1.0.** Not ready for production use: the
> API, the stored data and the configuration may change without notice.

## What it is for

Most people and small companies have more than one mail account: a
personal address at GMX or web.de, a company mailbox at Microsoft 365, an
info@ address at some hoster, maybe a Gmail account. Each speaks its own
dialect: IMAP here, Microsoft Graph there. Every tool that wants to work
with mail has to learn all of them and has to be given the passwords.

Mailbox Service turns that around. One service, running on your own machine
or server, holds the connections to all accounts. Everything else talks
to that service only, through one REST API that looks the same for every
provider. The service decides who may do what. A script, an app or an AI
assistant gets a token of its own. That token opens exactly the accounts
and operations it was given, nothing more.

That makes a few things simple that are hard otherwise:

- **Automation across accounts.** A script files invoices into a folder,
  archives newsletters, forwards order confirmations or reports what came
  in overnight. It works the same way for every account. It never sees a mail
  password, only its own token.
- **An AI assistant for your mail.** Through the MCP server, Claude or
  another assistant can search and read mail, summarize threads, sort
  messages and write replies. You decide by its rights whether it may
  send on its own or only prepare drafts for a person to send.
- **Controlled access.** A bookkeeping tool reads the invoice folder of one
  account and nothing else. A newsletter job sends from info@, to a fixed
  list of recipients, at most a few times a day. Every send is recorded.
- **One inbox for your own tools.** A dashboard or a small internal app
  lists, searches and answers mail from every account with one client.
- **Self-hosted.** The service stores the credentials encrypted. Mail
  goes straight from the provider to you, never through a third party's
  cloud.

## What it can do today

- **Accounts:** IMAP with SMTP for sending, set up from the address alone
  (autodiscovery), and Microsoft accounts (Outlook.com, Microsoft 365)
  over Microsoft Graph with OAuth sign-in. Credentials are encrypted
  (AES-256-GCM) under a master key kept outside the database.
- **Reading:** folders, lists and search, one account or all at once,
  messages as text and HTML, attachments, the raw source. Message ids stay
  the same when a message moves, kept by a background sync.
- **Writing:** flags, moving, deleting, folders, drafts, and sending with
  reply, reply to all and forward. A retried send is not sent twice
  (`Idempotency-Key`).
- **Users and rights:** users, roles and grants per account and per
  operation, API tokens, limits on sending (allowed recipients, sends per
  day) and an audit of every send.
- **MCP server:** reads, sorts, writes drafts and sends over stdio or
  streamable HTTP, offering only the tools its token may use. Mail content
  reaches the model marked as foreign text.
- **Configuration UI** in the browser under `/ui`: accounts, users,
  rights, tokens, reading and writing mail, the send audit.
- **Operation:** encrypted backup and restore, container images, a
  compose file.

Planned next: a change feed and webhooks, Gmail, JMAP. With a change feed
and webhooks, automation can react to new mail instead of asking for it.
The order is in [docs/ROADMAP.md](docs/ROADMAP.md).

## Providers

| Provider | Connected via | Credential | State |
|---|---|---|---|
| GMX, web.de, T-Online, Yahoo, AOL, iCloud, Posteo, mailbox.org, IONOS, Strato, own mail servers | IMAP + SMTP | app password | available |
| Microsoft 365, Outlook.com | Microsoft Graph | OAuth ([setup](docs/microsoft.md)) | available |
| Proton Mail | IMAP + SMTP through Proton Mail Bridge | Bridge password | IMAP, not tested |
| Gmail / Google Workspace | Gmail API | OAuth, with your own Google Cloud client | planned |
| Fastmail, Stalwart, other JMAP servers | JMAP | API token | planned |
| legacy mailboxes | POP3, reduced functionality | password | planned |

Not supportable: Tuta, which offers no IMAP and no API. Details per
provider in [docs/CONCEPT.md](docs/CONCEPT.md), section 5.3.

## The two packages

| Package | What it is | Runs | Read more |
|---|---|---|---|
| `benethos-mailbox-service` | the service: REST API, configuration UI, users and rights, accounts, encrypted credentials, provider adapters, background sync | permanently | [packages/mailbox-service](packages/mailbox-service/README.md) |
| `benethos-mailbox-mcp` | the MCP server, a client of the REST API only | per client over stdio, or as a server over HTTP | [packages/mailbox-mcp](packages/mailbox-mcp/README.md) |

```
 AI assistant ──MCP──► benethos-mailbox-mcp ──┐
 scripts, apps ───────────────────────────────┼─REST──► benethos-mailbox-service ──► IMAP / Graph / ...
 browser ─────────────────────────────── /ui ─┘
```

A release publishes both to PyPI and as container images on ghcr.io,
under the same version. Each package has its own README. It explains how
to install, start and configure it, with the container image and the
compose file.

## Getting started

1. Start the service and create the first user:
   [packages/mailbox-service](packages/mailbox-service/README.md#first-start).
2. Open `http://127.0.0.1:8080/ui`, sign in with the token and connect
   your accounts.
3. Give your scripts or your assistant a user with the rights they need,
   and for an assistant, add the MCP server to it:
   [packages/mailbox-mcp](packages/mailbox-mcp/README.md).

## Documentation

- [docs/CONCEPT.md](docs/CONCEPT.md): the design, the API, the security
  model
- [docs/ROADMAP.md](docs/ROADMAP.md): the phases and what is done
- [docs/microsoft.md](docs/microsoft.md): connecting Microsoft accounts
- [docs/openapi.json](docs/openapi.json): the API contract. A running
  service shows it at `/docs`
- [CHANGELOG.md](CHANGELOG.md)
- [SECURITY.md](SECURITY.md): how to report a vulnerability
- [containers/](containers/README.md): the Dockerfiles and the compose
  file

## Development

One uv workspace, one lockfile, two distributions.

```
uv sync
uv run pytest -q
uv run ruff check . && uv run ruff format --check .
uv run mypy
```

The tests run offline. Manual checks against real test accounts live in
`live/` and are described in [CLAUDE.md](CLAUDE.md), which also holds the
working rules for this repository.

## Licence

MIT, see [LICENSE](LICENSE).
