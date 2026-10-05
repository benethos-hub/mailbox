# Mailbox

[![CI](https://github.com/benethos-hub/mailbox/actions/workflows/ci.yml/badge.svg)](https://github.com/benethos-hub/mailbox/actions/workflows/ci.yml)
[![PyPI mailbox-service](https://img.shields.io/pypi/v/benethos-mailbox-service?label=PyPI%20mailbox-service)](https://pypi.org/project/benethos-mailbox-service/)
[![PyPI mailbox-mcp](https://img.shields.io/pypi/v/benethos-mailbox-mcp?label=PyPI%20mailbox-mcp)](https://pypi.org/project/benethos-mailbox-mcp/)
[![Container](https://img.shields.io/badge/ghcr.io-mailbox--service-2496ED?logo=docker&logoColor=white)](https://github.com/benethos-hub/mailbox/pkgs/container/benethos-mailbox-service)
[![Container](https://img.shields.io/badge/ghcr.io-mailbox--mcp-2496ED?logo=docker&logoColor=white)](https://github.com/benethos-hub/mailbox/pkgs/container/benethos-mailbox-mcp)
[![Python](https://img.shields.io/pypi/pyversions/benethos-mailbox-service)](https://pypi.org/project/benethos-mailbox-service/)
[![Coverage](https://img.shields.io/badge/coverage-97%25-brightgreen)](https://github.com/benethos-hub/mailbox/actions/workflows/ci.yml)
[![License](https://img.shields.io/badge/license-MIT-blue)](https://github.com/benethos-hub/mailbox/blob/main/LICENSE)

One REST API for all your mailboxes, whichever provider they are at, and
an MCP server on top. Scripts, tools and AI agents work with your mail
through one door you control.

> **Status: alpha, version 0.2.0.** Usable with real accounts for
> testing. The API and the configuration may still change. Stored data
> is carried forward by migrations.

## What it is for

Most people and small companies have more than one mail account: a
personal address at GMX or web.de, a company mailbox at Microsoft 365, an
info@ address at some hoster, maybe a Gmail account. Each speaks its own
dialect: IMAP here, Microsoft Graph there. Every tool that wants to work
with mail has to learn all of them and has to be given the passwords.

Mailbox turns that around. It has two parts. The Mailbox Service runs on
your own machine or server and holds the connections to all accounts.
Everything else talks to that service only, through one REST API that
looks the same for every provider. The MCP server builds on it and opens
it to AI agents. The service decides who may do what. A script, an app
or an AI agent gets a token of its own. That token opens exactly the
accounts and operations it was given, nothing more.

That makes a few things simple that are hard otherwise.

### Working with an AI agent in your mail

Through the MCP server, Claude or another AI agent works with every
account you gave it. A few requests it handles today:

- "What came in since last night?"
- "Move every invoice from Company XY to the folder Accounting."
- "Forward today's invoices to our tax advisor."
- "Show me all mail from Company XY between the 1st and the 15th of
  September."
- "Which mails with attachments came this week? Read the invoice and tell
  me the amount and the due date."
- "Sum up the mails about the offer and write a draft reply."
- "Mark last week's newsletters as read and move them to the archive."

Its rights decide whether it may send on its own or only leave drafts
for a person to send. A grant can also name the recipients it may write
to, such as the tax advisor's address alone, and how many mails it may
send a day. A mail to anyone else is refused. It can keep the agent to
some folders, such as the invoices, and end after a week.

### More uses

- **Controlled access.** A bookkeeping tool reads the invoice folder of
  one account and nothing else. It may neither send nor delete, and it
  never sees a mail password, only its own token.
- **Automation across accounts.** A script files invoices, archives
  newsletters and forwards order confirmations. It works the same way for
  GMX, Microsoft 365 and your own mail server.
- **Sending with guard rails.** A newsletter job sends from info@, to a
  fixed list of recipients, at most a few times a day.
- **React instead of polling.** Signed webhooks tell your own system
  about new mail, a ticket tool or an internal dashboard for example.
- **Traceable.** Every send is recorded in the audit: by whom, when and
  under which grant.
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
- **Changes:** a change feed names each message created, changed or
  deleted since a point you keep, in IMAP and Microsoft accounts, flags
  set in other mail clients included where the IMAP server offers
  CONDSTORE. Webhooks post the same events, signed, to a URL of your
  choice, a host in your local network included.
- **Users and rights:** users, roles and grants per account and per
  operation, down to folders, grants that expire, API tokens, limits on
  sending (allowed recipients, sends per day) and an audit of every send.
- **MCP server:** reads, sorts, writes drafts, sends and tells what is
  new, over stdio or streamable HTTP, offering only the tools its token
  may use. Mail content
  reaches the model marked as foreign text.
- **Configuration UI** in the browser under `/ui`: accounts, users,
  rights, tokens, reading and writing mail, the send audit, webhooks,
  the status of accounts and sync, the service log.
- **Operation:** encrypted backup and restore, container images, a
  compose file.

Planned next: threads across folders, Gmail and JMAP, and an audit of
administration beside the audit of sends. The order is in
[docs/ROADMAP.md](docs/ROADMAP.md).

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
 AI agent ──────MCP──► benethos-mailbox-mcp ──┐
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
2. Open `http://127.0.0.1:8080/ui`, sign in as `admin` with the
   one-time password, choose a password of your own and connect your
   accounts.
3. Give your scripts or your AI agent a user with the rights they need,
   and for an agent, add the MCP server to it:
   [packages/mailbox-mcp](packages/mailbox-mcp/README.md).

## Documentation

- [docs/CONCEPT.md](docs/CONCEPT.md): the design, the API, the security
  model
- [docs/ROADMAP.md](docs/ROADMAP.md): the phases and what is done
- [docs/ARCHITECTURE.md](docs/ARCHITECTURE.md): the layers, the modules
  and the rules for new code
- [docs/LIMITS.md](docs/LIMITS.md): every rate limit and how they work
  together
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
