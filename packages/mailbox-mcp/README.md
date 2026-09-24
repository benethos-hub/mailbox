# benethos-mailbox-mcp

MCP server for the Mailbox API. It reaches mail only through that REST
API, so the service `benethos-mailbox-api` has to be running.

```
MAILBOX_API_URL=http://127.0.0.1:8080 MAILBOX_API_TOKEN=... benethos-mailbox-mcp
```

stdio by default, `--transport streamable-http` for clients that connect to a
URL.
