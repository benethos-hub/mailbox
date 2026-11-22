# Concept of the Python client

The Python client, `mailbox-client`: section 8.2 of the
[concept](../mailbox-service/CONCEPT.md), which holds the overview and
every other section. The MCP server built on it, section 8, is in
[mailbox-mcp](../mailbox-mcp/CONCEPT.md).

## 8.2 The Python client

**Decided 2026-10-07:** a package of its own, `mailbox-client`
(`benethos-mailbox-client` on PyPI, no image), released with the
service and the MCP server under the same version. The MCP server is
built on it and pins it to that version. It depends on httpx alone and
never on the service, so the REST-only rule holds for it as for the MCP
server.

Two classes, `MailboxClient` for async code and `SyncMailboxClient` for
code without an event loop. Neither is built on the other: sync over
async needs an event loop per call, async over sync blocks the loop.
Each endpoint is described once, without I/O: its method, path, query,
body, and how its answer becomes a record. Both classes send those
descriptions with httpx and differ only in `await`. They read errors,
failures on the way and attachments in chunks the same way, through
the same code.

**Decided 2026-10-09:** it covers the whole REST API, not only what the
MCP server needs. Every operation is a method of both clients, named
like its `operationId`, and a test holds every operation of
`docs/mailbox-service/openapi.json` to one, but the route a link opens: its URL is the
credential, which another service holds, never a client with a token.
A new route is
incomplete until the client has its method. A secret the service
shows once comes as a `Secret`, kept out of `repr` and `str`.

Its interface has no stability promise yet.
