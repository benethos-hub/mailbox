# Working guidelines for the MCP server

The rules that hold for `mailbox-mcp` alone. The rules for the whole
repository, the golden rules among them, are in the
[CLAUDE.md of the root](../../CLAUDE.md): read it first.

## A REST client

The MCP server is a REST client (golden rule 6). It reaches mail only
through the REST API, with the client package `mailbox-client`, in
packages that cannot see the service. Anything the MCP server needs
that the API lacks is added to the API first.

## Its tools

`docs/mailbox-mcp/mcp-tools.json` holds the MCP server's tools as a
client lists them (golden rule 4). After any change to a tool,
regenerate it with
`uv run benethos-mailbox-mcp --list-tools > docs/mailbox-mcp/mcp-tools.json`
and review the diff of its descriptions like code.
