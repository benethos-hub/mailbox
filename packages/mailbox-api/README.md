# benethos-mailbox-api

> **Pre-alpha, version 0.0.1.** Not ready for production use: the API,
> the stored data and the configuration may change without notice.

The Mailbox API service: one REST API (OpenAPI 3.1) for several mail
providers and accounts. It runs permanently, owns the account store and the
provider connections, and fetches in the background.

```
MAILBOX_API_KEY=change-me benethos-mailbox-api serve
```

Interactive API docs at `http://127.0.0.1:8080/docs`. The MCP server for it
is the separate package `benethos-mailbox-mcp`.
