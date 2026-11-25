# Architecture of the MCP server

The modules of `mailbox-mcp`: section 3.3 of the
[architecture](../mailbox-service/ARCHITECTURE.md). The shape, the
layers of the service and the rules for every package (sections 5
to 17) are there.

## 3.3 The MCP server

The MCP server is a package of its own, built on the client. It
cannot import the service, and `tests/test_boundary.py` checks that.

```
packages/mailbox-mcp/
  src/benethos_mailbox_mcp/
    __main__.py         # python -m, calls cli.py
    cli.py              # the command line: options, MAILBOX_MCP_*, the
                        #   log in the lines of mailbox-common, its
                        #   tokens noted for masking, --list-tools, the
                        #   catalogue or the start over stdio or HTTP,
                        #   HTTP on an open address only with its guards
    server.py           # start: what the token may do, asked at the
                        #   service, then build_server: the MCP
                        #   library's server with the tools the token's
                        #   rights allow, each logged when it fails,
                        #   asked again while it runs. Server: that
                        #   library's class. build_catalogue: every
                        #   tool, none run but server_status
                        #   (CATALOGUE).
                        #   tools_json: the tools as a client lists
                        #   them, docs/mailbox-mcp/mcp-tools.json
    listeners.py        # the clients told that the tool list changed:
                        #   their connections, the announcement, the
                        #   bus of listen streams
    transport.py        # stdio, and streamable HTTP: bearer guard, host
                        #   check (uvicorn)
    tools/              # one module per kind with its part of TOOLS,
                        #   and what the kinds share
      base.py           # Tool, reads()/changes(), result(): text and
                        #   images, client(): the one of the server the
                        #   tool runs in, made in its lifespan, the
                        #   arguments the kinds share (AccountId,
                        #   MessageId, AttachmentId, DraftId, FolderId,
                        #   Limit, Cursor)
      compose.py        # what drafts and sending share: addresses, the
                        #   message a tool's arguments describe, and
                        #   those arguments (Addresses ... AttachFrom)
      accounts.py       # list_accounts, which reports the kinds
      reading.py        # folders, search, a message, a thread, what
                        #   is new,
                        #   attachments, a link to one for another
                        #   service
      writing.py        # change messages, create, rename or move a
                        #   folder
      drafts.py         # list, write, replace, delete drafts
      sending.py        # send a mail, send a draft, at once or through
                        #   the outbox, the outbox listed, a send cancelled
      status.py         # server_status: what runs, from memory, and
                        #   the service as the server last saw it
                        #   (Running, Seen), which saw and
                        #   seen_at_start keep
    render.py           # what the model sees of mail, marked as foreign
    answers.py          # what a tool answers as JSON, by name: one
                        #   TypedDict per answer, the output schema
    pdf.py              # PDF pages as PNG (pypdfium2)
    client.py           # the client package's MailboxClient, the
                        #   one way to the REST API
    models.py           # the client package's records
    errors.py           # ToolError with the kind of its failure, the
                        #   client's errors turned into one for the
                        #   model, why one failed for the log
                        #   (reason), what one tells of the token's
                        #   rights
    config.py           # Settings (MAILBOX_MCP_* and the service's
                        #   address and token, catalogue), the optional
                        #   .env and the folder of the system, from
                        #   mailbox-common, APP, the program's name,
                        #   and variable(): a setting's name in the
                        #   environment
```

The modules stand in lines, each importing only lines below:

```
 cli
 server · transport
 tools · listeners
 client · render · pdf
 models · errors · config · answers
```

`tests/test_architecture.py` of the MCP package keeps the modules in
these lines, the tools behind their package, and one home per library.
The command line imports nothing of `tools`: the tools and what the
token may do are `server`'s.

**A tool of the MCP server** is a function in `tools/<kind>.py` with
its line in that module's `TOOLS`: its title, the rights it needs, and
whether it is read-only, destructive or idempotent. The server
registers it only for a token that holds one of those rights, and the
catalogue registers every tool. The
function is thin: it names what it wants in its own terms, the client
package makes the request, and `render.py` shapes what the model sees, with
mail content inside the foreign-content marker. An answer in JSON is a
`TypedDict` of `answers.py`, filled by `render.py`. A tool never spells
out a path, a query name or a field of the API, and never speaks HTTP
itself. Its docstring is the description the model reads. An argument
may carry a description of its own and its bounds, in `Annotated` with
`Field`. The server checks the bounds before the tool runs. Its test is
in `tests/tools/`, against `httpx.MockTransport`. The tables of the
package's README and of the root README name it, and
`docs/mailbox-mcp/mcp-tools.json` holds it as a client lists it
(`test_tools_snapshot.py`). The manifest of the Claude Desktop bundle,
`.github/publish/mcpb/manifest.json`, lists it with the first sentence
of its description (`test_mcpb.py`).
