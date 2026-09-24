# benethos-mailbox-mcp

MCP server for the Mailbox API. It reaches mail only through that REST
API, so the service `benethos-mailbox-api` has to be running. It runs over
stdio: the MCP client starts it and it ends with the client.

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

## Tools

At start the server asks `/v1/me` what its token may do and offers only
the tools that fit:

| Tool | Needs | What it does |
|---|---|---|
| `list_accounts` | – | the accounts, their addresses, what may be done on each |
| `list_folders` | `mail.read` | folders with id, name, role and counts |
| `search_messages` | `mail.read` | find mail by text, sender, recipient, subject, days, flags, attachments; one account or all |
| `get_message` | `mail.read` | one mail as plain text, cut to `max_chars` |

Mail content comes back inside `<mail-content>` markers: it is written by
strangers and is data, not instructions. HTML is turned into text without
its hidden parts.
