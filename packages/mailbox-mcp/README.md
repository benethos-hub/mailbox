# mailbox-mcp

[![CI](https://github.com/benethos-hub/mailbox/actions/workflows/ci.yml/badge.svg)](https://github.com/benethos-hub/mailbox/actions/workflows/ci.yml)
[![PyPI mailbox-mcp](https://img.shields.io/pypi/v/benethos-mailbox-mcp?label=PyPI%20mailbox-mcp)](https://pypi.org/project/benethos-mailbox-mcp/)
[![Container](https://img.shields.io/badge/ghcr.io-mailbox--mcp-2496ED?logo=docker&logoColor=white)](https://github.com/benethos-hub/mailbox/pkgs/container/benethos-mailbox-mcp)
[![Python](https://img.shields.io/pypi/pyversions/benethos-mailbox-mcp)](https://pypi.org/project/benethos-mailbox-mcp/)
[![License](https://img.shields.io/badge/license-MIT-blue)](https://github.com/benethos-hub/mailbox/blob/main/LICENSE)

> **Alpha, version 0.2.0.** Usable with real accounts for testing. The
> API and the configuration may still change. Stored data is carried
> forward by migrations.

The MCP server of Mailbox, on PyPI as `benethos-mailbox-mcp`. It gives
Claude and other AI
assistants your mailboxes, as far as its token allows. It searches and
reads mail, tells what is new since it last looked, looks at attachments
(PDF pages as images), sorts messages, writes drafts and, if you let it,
sends.

It reaches mail only through the REST API of
[`mailbox-service`](https://github.com/benethos-hub/mailbox/tree/main/packages/mailbox-service),
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
read and to ask what is new, `mail.write` to sort and file, `drafts` to write drafts, `send` to
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
| – | `MAILBOX_SERVICE_TOKEN` | none and required, the token of the user it acts as |
| – | `MAILBOX_SERVICE_ALLOW_HTTP` | off. `1` allows `http` to a host other than this machine |
| `--transport` | `MAILBOX_MCP_TRANSPORT` | `stdio`, or `streamable-http` |
| `--host` | `MAILBOX_MCP_HOST` | `127.0.0.1` |
| `--port` | `MAILBOX_MCP_PORT` | `8000` |
| `--path` | `MAILBOX_MCP_PATH` | `/mcp` |
| `--allowed-hosts` | `MAILBOX_MCP_ALLOWED_HOSTS` | none, comma-separated Host values |
| `--allowed-origins` | `MAILBOX_MCP_ALLOWED_ORIGINS` | none, comma-separated |
| `--log-level` | `MAILBOX_MCP_LOG_LEVEL` | `INFO` |
| – | `MAILBOX_MCP_BEARER_TOKEN` | none, what HTTP clients must send |
| `--env-file` | `MAILBOX_MCP_ENV_FILE` | a settings file, see below |

The command line wins over the environment, the environment over a
settings file. An MCP client usually passes the settings in its own
configuration. Without a client, or for a server over HTTP, they can
go into a `.env` file. The first that exists is read: the file named
with `--env-file` or `MAILBOX_MCP_ENV_FILE`, which must exist, then
`config/benethos-mailbox-mcp/.env` in the working directory, then `.env`
in the settings folder of the operating system:
`%LOCALAPPDATA%\benethos-mailbox-mcp\config` on Windows,
`~/.config/benethos-mailbox-mcp` on Linux,
`~/Library/Application Support/benethos-mailbox-mcp/config` on macOS.
It sets only `MAILBOX_MCP_*` and `MAILBOX_SERVICE_*`. It holds the API
token, so keep it readable by its owner alone. Template:
[config/benethos-mailbox-mcp/.env.example](https://github.com/benethos-hub/mailbox/blob/main/config/benethos-mailbox-mcp/.env.example).

`MAILBOX_SERVICE_URL` takes `https` anywhere and `http` to this machine
only (`localhost`, `127.0.0.1`, `::1`), since the token goes with every
request. For `http` to another host, e.g. a container beside it, set
`MAILBOX_SERVICE_ALLOW_HTTP=1`. Without it the server does not start.

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
Tags: the version (`0.2.0`), the minor version (`0.2`) and `latest`.

### With docker run

Next to a service container named `mailbox-service` (see the service's
README), in a network both share:

```sh
docker network create mailbox
docker network connect mailbox mailbox-service

docker run -d --name mailbox-mcp --restart unless-stopped --network mailbox \
  -p 127.0.0.1:8000:8000 --read-only --tmpfs /tmp \
  -e MAILBOX_SERVICE_URL=http://mailbox-service:8080 \
  -e MAILBOX_SERVICE_ALLOW_HTTP=1 \
  -e MAILBOX_SERVICE_TOKEN=<token> \
  -e MAILBOX_MCP_BEARER_TOKEN=<a long random token> \
  -e MAILBOX_MCP_ALLOWED_HOSTS=127.0.0.1:8000,localhost:8000 \
  ghcr.io/benethos-hub/benethos-mailbox-mcp:0.2.0
```

Inside the container the server binds to `0.0.0.0`. So
`MAILBOX_MCP_ALLOWED_HOSTS` names the Host values clients use: the port as
published on the host, or the host name behind a proxy.

### Beside a service in operation

[containers/production/](https://github.com/benethos-hub/mailbox/tree/main/containers/production)
runs the service. The MCP server acts as one user, with that user's
token, so each client has one of its own. Usually the client starts it
over stdio as above, with `MAILBOX_SERVICE_URL` set to the service's
address, for example `https://<MAILBOX_DOMAIN>` behind its Caddy. For a
client that connects over HTTP, instances of this image run beside the
service with the profile `mcp`, one per token, from the template
`mcp.yaml`. Caddy can route to each under a path of its own, such as
`https://<MAILBOX_DOMAIN>/mcp/agent`. Its
[README](https://github.com/benethos-hub/mailbox/blob/main/containers/production/README.md#mcp-server-instances)
has the steps, also for an instance on another host. For
development,
[containers/dev/compose.yaml](https://github.com/benethos-hub/mailbox/blob/main/containers/dev/compose.yaml)
starts it beside a service built from the repository, with the profile
`mcp`.

## Tools

At start the server asks `/v1/me` what its token may do and offers only
the tools that fit:

| Tool | Needs | What it does |
|---|---|---|
| `list_accounts` | – | the accounts, their addresses, what may be done on each, the limits on sending and a warning where the token may read and send anywhere |
| `list_folders` | `mail.read` | folders with id, name, role and counts |
| `search_messages` | `mail.read` | find mail by text, sender, recipient, subject, days, flags, attachments, in one account or all |
| `get_message` | `mail.read` | one mail as plain text, cut to `max_chars` |
| `get_attachment` | `mail.read` | an attachment: images up to 5 MB as images, PDF pages as PNG images (`first_page`, `pages`, up to 10, 12 megapixels together), text as text, HTML as the text a reader sees, other types by name only |
| `whats_new` | `mail.read` | mail created, updated or deleted since the `state` of an earlier call, ids only, in one account or all |
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
not instructions. A list of messages, which is JSON, carries a `note`
saying the same of `from` and `subject`, a list of drafts of `to` and
`subject`, which a reply takes from the mail it answers. HTML is turned
into text without its hidden parts: text not shown, too small or faint
to read, pushed off the page or in the colour of its own background.
