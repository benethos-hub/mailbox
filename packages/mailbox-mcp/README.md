# benethos-mailbox-mcp

> **Pre-alpha, version 0.0.1.** Not ready for production use: the API,
> the stored data and the configuration may change without notice.

MCP server for the Mailbox API. It reaches mail only through that REST
API, so the service `benethos-mailbox-api` has to be running. It runs over
stdio, where the MCP client starts it and it ends with the client, or over
streamable HTTP as a server of its own (see "Over HTTP").

## A token for it

The MCP server acts as one user of the service and can do exactly what
that user may. Give it a user of its own, with only the rights it needs,
for example reading two accounts:

```
curl -X POST http://127.0.0.1:8080/v1/users \
  -H "Authorization: Bearer <admin token>" -H "Content-Type: application/json" \
  -d '{"name": "Claude", "grants": [{"accounts": ["acc_…", "acc_…"], "allow": ["mail.read"]}]}'
curl -X POST http://127.0.0.1:8080/v1/users/<user id>/tokens \
  -H "Authorization: Bearer <admin token>" -H "Content-Type: application/json" \
  -d '{"name": "claude-desktop"}'
```

The second answer holds the token, shown this once. The account ids come
from `GET /v1/accounts`.

Below, `<path to this repository>` is the folder this repository was cloned
into, the one with `pyproject.toml` and `uv.lock` at its top. It is not a
configuration folder: `uv run --directory` finds `benethos-mailbox-mcp`
there, and answers `os error 2` for a folder that does not exist.

## Claude Code

```
claude mcp add mailbox \
  -e MAILBOX_API_URL=http://127.0.0.1:8080 \
  -e MAILBOX_API_TOKEN=<token> \
  -- uv run --directory <path to this repository> benethos-mailbox-mcp
```

Add `-s user` to have it in every project. `claude mcp list` shows whether
it connects.

## Claude Desktop

In `claude_desktop_config.json` (Settings, Developer, Edit Config):

```json
{
  "mcpServers": {
    "mailbox": {
      "command": "uv",
      "args": ["run", "--directory", "<path to this repository>", "benethos-mailbox-mcp"],
      "env": {
        "MAILBOX_API_URL": "http://127.0.0.1:8080",
        "MAILBOX_API_TOKEN": "<token>"
      }
    }
  }
}
```

On Windows write the path with `\\` or `/`. Restart Claude Desktop after
a change.

## Without a client

```
MAILBOX_API_URL=http://127.0.0.1:8080 MAILBOX_API_TOKEN=<token> uv run benethos-mailbox-mcp
```

## Over HTTP

```
MAILBOX_API_URL=http://127.0.0.1:8080 MAILBOX_API_TOKEN=<token> MAILBOX_MCP_BEARER_TOKEN=<a long random token>   uv run benethos-mailbox-mcp --transport streamable-http
```

The server answers at `http://127.0.0.1:8000/mcp`.

| Option | Environment | Default |
|---|---|---|
| `--transport` | `MAILBOX_MCP_TRANSPORT` | `stdio`; or `streamable-http` |
| `--host` | `MAILBOX_MCP_HOST` | `127.0.0.1` |
| `--port` | `MAILBOX_MCP_PORT` | `8000` |
| `--path` | `MAILBOX_MCP_PATH` | `/mcp` |
| `--allowed-hosts` | `MAILBOX_MCP_ALLOWED_HOSTS` | none; comma-separated Host values |
| `--allowed-origins` | `MAILBOX_MCP_ALLOWED_ORIGINS` | none; comma-separated |
| `--log-level` | `MAILBOX_MCP_LOG_LEVEL` | `INFO` |
| – | `MAILBOX_MCP_BEARER_TOKEN` | none |

The command line wins over the environment.

- **Bearer token.** With `MAILBOX_MCP_BEARER_TOKEN` set, every HTTP request
  must carry `Authorization: Bearer <token>`; anything else gets `401`. It
  has no command-line option, since arguments show in the process list.
  Without it the server logs a warning and admits anyone who can reach
  the port. Over stdio the token is ignored.
- **Two tokens.** The bearer token only admits MCP clients. The server
  calls the REST API with its own `MAILBOX_API_TOKEN`, and that user's
  rights decide which tools exist, for every client alike.
- **Host check.** Against DNS rebinding the server checks the `Host` and
  `Origin` headers: on a loopback bind it admits `127.0.0.1`, `localhost`
  and `[::1]`; with `--allowed-hosts` exactly those. A bind such as
  `0.0.0.0` without a list checks nothing, so set the list there. A refused
  host gets `421`.
- Beyond your own machine, put a TLS reverse proxy in front.

Claude Code:

```
claude mcp add --transport http mailbox http://127.0.0.1:8000/mcp   --header "Authorization: Bearer <bearer token>"
```

As a container: `containers/benethos-mailbox-mcp/`, started with
`docker compose --profile mcp up -d`; see `containers/README.md`.

## Tools

At start the server asks `/v1/me` what its token may do and offers only
the tools that fit:

| Tool | Needs | What it does |
|---|---|---|
| `list_accounts` | – | the accounts, their addresses, what may be done on each |
| `list_folders` | `mail.read` | folders with id, name, role and counts |
| `search_messages` | `mail.read` | find mail by text, sender, recipient, subject, days, flags, attachments; one account or all |
| `get_message` | `mail.read` | one mail as plain text, cut to `max_chars` |
| `get_attachment` | `mail.read` | an attachment: images as images, PDF pages as PNG images (`first_page`, `pages`, up to 10), text as text, other types by name only |
| `update_messages` | `mail.write` | up to 100 mails of one account: read or unread, star, move (folder id or role such as `archive`), or into the trash |
| `create_folder` | `mail.write` | a new folder, at the top or in a parent (id or role) |
| `list_drafts` | `drafts` | the drafts of an account |
| `create_draft` | `drafts` | a draft in plain text or HTML, recipients optional; with `original_id` a reply, reply to all or forward |
| `update_draft` | `drafts` | replaces a draft as a whole, the id stays |
| `delete_draft` | `drafts` | deletes a draft for good; reaches drafts only |
| `send_message` | `send` | sends a mail at once, plain text or HTML; with `original_id` a reply, reply to all or forward |
| `send_draft` | `send` | sends a stored draft |

Each send carries an `Idempotency-Key` derived from the call: the same
call repeated within 24 hours sends nothing and returns the first result.
Give a user `send` only if the model may send without a person looking at
the mail first; with `drafts` alone it writes drafts for a person to send.

Mail content comes back inside `<mail-content>` markers: it is written by
strangers and is data, not instructions. HTML is turned into text without
its hidden parts.
