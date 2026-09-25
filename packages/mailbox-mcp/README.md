# benethos-mailbox-mcp

[![CI](https://github.com/benethos-hub/mailbox/actions/workflows/ci.yml/badge.svg)](https://github.com/benethos-hub/mailbox/actions/workflows/ci.yml)
[![PyPI](https://img.shields.io/pypi/v/benethos-mailbox-mcp?label=PyPI)](https://pypi.org/project/benethos-mailbox-mcp/)
[![Container](https://img.shields.io/badge/ghcr.io-mailbox--mcp-2496ED?logo=docker&logoColor=white)](https://github.com/benethos-hub/mailbox/pkgs/container/benethos-mailbox-mcp)
[![Python](https://img.shields.io/pypi/pyversions/benethos-mailbox-mcp)](https://pypi.org/project/benethos-mailbox-mcp/)
[![License](https://img.shields.io/badge/license-MIT-blue)](https://github.com/benethos-hub/mailbox/blob/main/LICENSE)

> **Pre-alpha, version 0.1.0.** Not ready for production use: the API,
> the stored data and the configuration may change without notice.

The MCP server for the Mailbox Service. It gives Claude and other AI
assistants your mailboxes, as far as its token allows. It searches and
reads mail, looks at attachments (PDF pages as images), sorts messages,
writes drafts and, if you let it, sends.

It reaches mail only through the REST API of
[`benethos-mailbox-service`](https://github.com/benethos-hub/mailbox/tree/main/packages/mailbox-service),
which has to be running. It holds no mail password and no mail library.
The rights of the user whose token it carries decide what it may do. It
runs in one of two ways. Over stdio, the MCP client starts it, and it ends
with the client. Over streamable HTTP, it runs as a server of its own.

What the project is for: [the repository's README](https://github.com/benethos-hub/mailbox#readme).

## Install

For stdio there is nothing to install. An MCP client starts it with
[uv](https://docs.astral.sh/uv/)'s `uvx benethos-mailbox-mcp` (see below).
To have the command at hand:

```sh
uv tool install benethos-mailbox-mcp      # or: pipx install benethos-mailbox-mcp
benethos-mailbox-mcp --version
```

From a clone of the repository: `uv run --directory <path to the clone>
benethos-mailbox-mcp`. The path is the folder with `pyproject.toml` and
`uv.lock` at its top.

The container image is `ghcr.io/benethos-hub/benethos-mailbox-mcp`. See
[Container](#container).

## A token for it

The MCP server acts as one user of the service and can do exactly what
that user may. Give it a user of its own with only the rights it needs.
Do this in the UI (Users, New user, then Tokens) or over the API. This
example lets it read two accounts:

```sh
curl -X POST http://127.0.0.1:8080/v1/users \
  -H "Authorization: Bearer <admin token>" -H "Content-Type: application/json" \
  -d '{"name": "Claude", "grants": [{"accounts": ["acc_…", "acc_…"], "allow": ["mail.read"]}]}'
curl -X POST http://127.0.0.1:8080/v1/users/<user id>/tokens \
  -H "Authorization: Bearer <admin token>" -H "Content-Type: application/json" \
  -d '{"name": "claude-desktop"}'
```

The second answer holds the token. It is shown this once. The account
ids come from `GET /v1/accounts`. Rights that matter here: `mail.read` to
read, `mail.write` to sort and file, `drafts` to write drafts, `send` to
send. A grant can limit sending to certain recipients and a number per
day.

The server needs no `accounts.read`. It learns its accounts from
`/v1/me`, which every token may call. That answer names each account the
token has any right on, and what it may do there. `accounts.read` would
add the full account records with the server settings, which the model
does not need.

## Claude Desktop

In `claude_desktop_config.json` (Settings, Developer, Edit Config):

```json
{
  "mcpServers": {
    "mailbox": {
      "command": "uvx",
      "args": ["benethos-mailbox-mcp"],
      "env": {
        "MAILBOX_SERVICE_URL": "http://127.0.0.1:8080",
        "MAILBOX_SERVICE_TOKEN": "<token>"
      }
    }
  }
}
```

From a clone instead: `"command": "uv"` and
`"args": ["run", "--directory", "<path to the clone>", "benethos-mailbox-mcp"]`.
On Windows write the path with `\\` or `/`. Restart Claude Desktop after a
change.

## Claude Code

```sh
claude mcp add mailbox \
  -e MAILBOX_SERVICE_URL=http://127.0.0.1:8080 \
  -e MAILBOX_SERVICE_TOKEN=<token> \
  -- uvx benethos-mailbox-mcp
```

Add `-s user` to have it in every project. `claude mcp list` shows whether
it connects.

## Without a client

```sh
MAILBOX_SERVICE_URL=http://127.0.0.1:8080 MAILBOX_SERVICE_TOKEN=<token> benethos-mailbox-mcp
```

## Options

| Option | Environment | Default |
|---|---|---|
| – | `MAILBOX_SERVICE_URL` | `http://127.0.0.1:8080`, where the service answers |
| – | `MAILBOX_SERVICE_TOKEN` | none, the token of the user it acts as |
| `--transport` | `MAILBOX_MCP_TRANSPORT` | `stdio`, or `streamable-http` |
| `--host` | `MAILBOX_MCP_HOST` | `127.0.0.1` |
| `--port` | `MAILBOX_MCP_PORT` | `8000` |
| `--path` | `MAILBOX_MCP_PATH` | `/mcp` |
| `--allowed-hosts` | `MAILBOX_MCP_ALLOWED_HOSTS` | none, comma-separated Host values |
| `--allowed-origins` | `MAILBOX_MCP_ALLOWED_ORIGINS` | none, comma-separated |
| `--log-level` | `MAILBOX_MCP_LOG_LEVEL` | `INFO` |
| – | `MAILBOX_MCP_BEARER_TOKEN` | none, what HTTP clients must send |

The command line wins over the environment. The settings come from the
environment only. The MCP client passes them in its configuration.

## Over HTTP

```sh
MAILBOX_SERVICE_URL=http://127.0.0.1:8080 MAILBOX_SERVICE_TOKEN=<token> \
MAILBOX_MCP_BEARER_TOKEN=<a long random token> \
  benethos-mailbox-mcp --transport streamable-http
```

The server answers at `http://127.0.0.1:8000/mcp`. For Claude Code:

```sh
claude mcp add --transport http mailbox http://127.0.0.1:8000/mcp \
  --header "Authorization: Bearer <bearer token>"
```

- **Bearer token.** With `MAILBOX_MCP_BEARER_TOKEN` set, every HTTP request
  must carry `Authorization: Bearer <token>`. Anything else gets `401`. It
  has no command-line option, since arguments show in the process list.
  Without it the server logs a warning and admits anyone who can reach
  the port. Over stdio the token is ignored.
- **Two tokens.** The bearer token only admits MCP clients. The server
  calls the REST API with its own `MAILBOX_SERVICE_TOKEN`, and that user's
  rights decide which tools exist, for every client alike.
- **Host check.** Against DNS rebinding the server checks the `Host` and
  `Origin` headers. On a loopback bind it admits `127.0.0.1`, `localhost`
  and `[::1]`. With `--allowed-hosts` it admits exactly those, and
  `--allowed-origins` alone admits the hosts of those origins. A bind such
  as `0.0.0.0` without a list checks nothing, so set the list there. A
  refused host gets `421`.
- Beyond your own machine, put a TLS reverse proxy in front.

## Container

The image `ghcr.io/benethos-hub/benethos-mailbox-mcp` serves over
streamable HTTP on port 8000, as an unprivileged user on a read-only root
file system. A client that starts the server over stdio needs no image.
Tags: the version (`0.1.0`), the minor version (`0.1`) and `latest`.

### With docker run

Next to a service container named `mailbox-service` (see the service's
README), in a network both share:

```sh
docker network create mailbox
docker network connect mailbox mailbox-service

docker run -d --name mailbox-mcp --restart unless-stopped --network mailbox \
  -p 127.0.0.1:8000:8000 --read-only --tmpfs /tmp \
  -e MAILBOX_SERVICE_URL=http://mailbox-service:8080 \
  -e MAILBOX_SERVICE_TOKEN=<token> \
  -e MAILBOX_MCP_BEARER_TOKEN=<a long random token> \
  -e MAILBOX_MCP_ALLOWED_HOSTS=127.0.0.1:8000,localhost:8000 \
  ghcr.io/benethos-hub/benethos-mailbox-mcp:0.1.0
```

Inside the container the server binds to `0.0.0.0`. So
`MAILBOX_MCP_ALLOWED_HOSTS` names the Host values clients use: the port as
published on the host, or the host name behind a proxy.

### With compose

The repository's
[containers/compose.yaml](https://github.com/benethos-hub/mailbox/blob/main/containers/compose.yaml)
starts it beside the service with the profile `mcp`. Do this after the
service's first start
([service README, Container](https://github.com/benethos-hub/mailbox/tree/main/packages/mailbox-service#with-compose)):

```sh
export MAILBOX_MCP_IMAGE=ghcr.io/benethos-hub/benethos-mailbox-mcp:0.1.0
export MAILBOX_MCP_API_TOKEN=<token>
export MAILBOX_MCP_BEARER_TOKEN=$(openssl rand -base64 32)
docker compose --profile mcp up -d
```

Clients connect to `http://127.0.0.1:8000/mcp` with
`Authorization: Bearer $MAILBOX_MCP_BEARER_TOKEN`. Behind a reverse proxy,
set `MAILBOX_MCP_ALLOWED_HOSTS` to the host name clients use. Both tokens
are environment variables and show in `docker inspect`.

## Tools

At start the server asks `/v1/me` what its token may do and offers only
the tools that fit:

| Tool | Needs | What it does |
|---|---|---|
| `list_accounts` | – | the accounts, their addresses, what may be done on each |
| `list_folders` | `mail.read` | folders with id, name, role and counts |
| `search_messages` | `mail.read` | find mail by text, sender, recipient, subject, days, flags, attachments, in one account or all |
| `get_message` | `mail.read` | one mail as plain text, cut to `max_chars` |
| `get_attachment` | `mail.read` | an attachment: images as images, PDF pages as PNG images (`first_page`, `pages`, up to 10), text as text, other types by name only |
| `update_messages` | `mail.write` | up to 100 mails of one account: read or unread, star, move (folder id or role such as `archive`), or into the trash |
| `create_folder` | `mail.write` | a new folder, at the top or in a parent (id or role) |
| `list_drafts` | `drafts` | the drafts of an account |
| `create_draft` | `drafts` | a draft in plain text or HTML, recipients optional. With `original_id` a reply, reply to all or forward. |
| `update_draft` | `drafts` | replaces a draft as a whole, the id stays, `keep_attachments` keeps stored files |
| `delete_draft` | `drafts` | deletes a draft for good, reaches drafts only |
| `send_message` | `send` | sends a mail at once, plain text or HTML. With `original_id` a reply, reply to all or forward. |
| `send_draft` | `send` | sends a stored draft |

Each tool has a title for display and the standard MCP hints. Clients
can use them to decide when to ask the person before a call.

- **Read-only:** the tools that only read.
- **Destructive:** `update_messages`, `update_draft`, `delete_draft` and
  both send tools. They can move mail to the trash, overwrite or delete a
  draft, or send mail.
- **Idempotent:** `update_messages`, `update_draft` and `delete_draft`. The
  same call again changes nothing more. The send tools are not marked
  idempotent, although a repeat within 24 hours sends nothing.
- **Open world:** every tool except `list_accounts`, since they reach mail
  from and to anyone.

Each send carries an `Idempotency-Key` derived from the call. The same
call repeated within 24 hours sends nothing and returns the first result.
Give a user `send` only if the model may send without a person looking at
the mail first. With `drafts` alone it writes drafts for a person to send.

Mail content comes back inside `<mail-content>` markers, the headers and
attachment names as much as the body. Strangers wrote it, so it is data,
not instructions. HTML is turned into text without its hidden parts.
