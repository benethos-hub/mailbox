# Architecture: the modules of the client, the MCP server and what they share

Part of the [architecture](../ARCHITECTURE.md): sections 3.2 to 3.4.

## 3.2 The client

The Python client of the REST API is a package of its own. It cannot
import the service or the MCP server, and its
`tests/test_architecture.py` checks that, with the lines below, a
package counting as one, httpx only in the modules that make or read
a request or check an address, and the endpoints reached through
their package alone.

```
packages/mailbox-client/
  src/benethos_mailbox_client/
    __init__.py         # what a caller imports: both clients, the
                        #   records, the errors, message_body(),
                        #   from_environment()
    client.py           # MailboxClient: sends the calls with
                        #   httpx.AsyncClient, one line per method
    sync.py             # SyncMailboxClient: the same calls with
                        #   httpx.Client
    endpoints/          # each endpoint once, one module per resource
                        #   of the API, with the readings of its
                        #   records. Sends nothing
      me.py             # get_me(): the caller and its accounts, the
                        #   catalogue of rights
      health.py         # whether the service answers
      accounts.py       # list, connect, read, change, verify, remove,
                        #   the names receiving servers wrote
      discovery.py      # discovery, the sign-in with a code
      folders.py        # the folders of an account
      messages.py       # lists and search in one account or across,
                        #   a message and its source, flags, keywords
                        #   and moves for one or many, deleting, and
                        #   the page the drafts read too
      changes.py        # the change feed of one account or of all
      attachments.py    # an attachment's bytes, a link to it
      threads.py        # the threads of a folder, one thread
      drafts.py         # list, write, replace, delete drafts
      sending.py        # send a message, send a draft
      sends.py          # the audit of sends
      users.py          # users, a password set
      tokens.py         # a user's tokens
      roles.py          # roles
      rights.py         # grants read and written, for users and roles
      factors.py        # a user's second factor
      webhooks.py       # webhooks, a new signing secret
      audit.py          # the audit of administration
      status.py         # the state of the service
      readings.py       # what the resources read alike: times, pages
      compose.py        # message_body: what drafts and sending share
      generic.py        # request(): any route, its JSON as it comes
    answers.py          # an answer read: its JSON, the error envelope
                        #   as ApiError, an answer that cannot be
                        #   read, a failure on the way
    attachments.py      # an attachment's bytes in chunks, up to a
                        #   limit, what its headers say
    environment.py      # the address and the token: from the
                        #   environment (from_environment) or given,
                        #   checked before a client is made
    calls.py            # Call: the request an endpoint describes,
                        #   its path below /v1, the timeouts. Awaiting
                        #   and blocking make a client's method of it
    models/             # the records the clients answer with, one
                        #   module per resource as in endpoints/, every
                        #   one offered by its __init__.py
      me.py             # the caller, its accounts, its sending limits
      health.py         # the service's health and version
      accounts.py       # an account, its stored credentials and marks,
                        #   the names receiving servers wrote
      discovery.py      # what discovery found, a sign-in with a code
      folders.py        # a folder
      messages.py       # a message and its summary with its sender
                        #   check, a page, a batch's outcome
      changes.py        # the changes since a state
      attachments.py    # an attachment's bytes, a link to an attachment
      threads.py        # a thread and its summary
      sending.py        # a recipient, what a send answered
      sends.py          # a record of the audit of sends
      rights.py         # a grant, the catalogue of rights
      users.py          # a user, a password made for one
      tokens.py         # a token, a new one with its secret
      roles.py          # a role
      factors.py        # a second factor and its devices
      webhooks.py       # a webhook, its posts, a new one or a new
                        #   signing secret
      audit.py          # an activity of the audit
      status.py         # the worker and the health of each account
      paging.py         # Paged: a page of records and its cursor
      secrets.py        # Secret: what the service shows once, kept out
                        #   of repr and str
    errors.py           # MailboxError and its subclasses
```

The modules stand in lines, each importing only lines below:

```
 client · sync
 endpoints
 answers · attachments · environment
 calls
 models · errors
```

**An endpoint of the client** is a function in the module of its
resource in `endpoints/` that answers a `Call`, named like the
operation's `operationId`, and a one-line method on each client made
from it: `list_users = awaiting(endpoints.list_users)` in
`MailboxClient`, `blocking(...)` in `SyncMailboxClient` (`calls.py`).
The method takes the function's arguments and has its name, docstring
and signature. Its test is in `tests/endpoints/`, in the file of that
module, and runs for both clients. Neither client
knows a path or a field: when the two differ in more than `await`,
the difference belongs in `endpoints/`, `calls.py` or `answers.py`.

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
                        #   them, docs/mcp-tools.json
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
      sending.py        # send a mail, send a draft
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
`docs/mcp-tools.json` holds it as a client lists it
(`test_tools_snapshot.py`). The manifest of the Claude Desktop bundle,
`.github/publish/mcpb/manifest.json`, lists it with the first sentence
of its description (`test_mcpb.py`).

## 3.4 What the service and the MCP server share

What the service and the MCP server both need is a package of its own,
`mailbox-common`, since the MCP server cannot see the service. It sees
neither of them, nor the client. It is made of groups, one per concern,
so a group can be cut out as a package of its own later.

```
packages/mailbox-common/
  src/benethos_mailbox_common/
    __init__.py         # __version__, no group imported
    mail/               # mail itself, nothing of Mailbox
      plaintext.py      # the visible text of an HTML body: the mail page
                        #   shows it, the model of the MCP server reads it
      addresses.py      # readable: Name <email>, quoted for a form
      marks.py          # the marks of RFC 8621 and their words, as
                        #   the UI and the MCP server show them
    log/                # the lines of a log and the secrets kept out
      lines.py          # format, levels, log_time, plain or in colour
                        #   on a terminal, a program's own lines through
                        #   line_of, the stderr handler
      redact.py         # secrets noted once, masked in every text,
                        #   forget for tests
    paths/              # where a program keeps its files (platformdirs)
      folders.py        # named_file, system_folders: SystemFolders
    settings/           # a program's settings (pydantic-settings)
      files.py          # FileSettings, the base of a program's
                        #   Settings, and load: the command line, the
                        #   environment, the file, the defaults
    values/             # values written one way
      canonical.py      # JSON: compact to send, canonical to hash
      sizes.py          # MIB, and a size in megabytes for a message
      secret.py         # new_id, token, digest, hmac_hex, same. Every
                        #   length with its reason
      text.py           # text on one line: escaped for the log, joined
                        #   for a header, has_break and ends_line for
                        #   the wire, plural
```

- **What goes in.** What at least two packages need. A guide, not a
  rule, as for `common/` in section 2: what only the service needs
  stays in its `common/`, and a helper may move once a second package
  wants it. No test enforces it.
- **A group stands alone.** A module imports only inside its group. A
  group offers its modules in `__all__` (section 5, rules 3 and 4), and
  a caller imports a module from its group, never deeper:
  `from benethos_mailbox_common.log import lines`, then
  `lines.stderr_handler(...)`. Where the module's name is taken in the
  caller, it is imported under another, with a comment.
- **Libraries.** The standard library alone, but for a group that names
  a library. That library is an extra named after the group, never
  after the library: `paths` brings platformdirs, `settings`
  pydantic-settings. A group's module
  that misses its extra says which one. `all` names every extra. An
  extra is worth it when a user of the package does not need the group,
  or the library is heavy. Tests and CI install every extra, and CI
  runs the package once without any.
- **The pin is exact.** The service and the MCP server depend on
  `benethos-mailbox-common[paths,settings]==X.Y.Z`, the version of
  the release.
  So groups, paths and extras may change inside a release, and an
  operator never types an extra.
- **A new module** goes into the group of its concern, with its test in
  the same folder under `tests/`. It returns a record and takes plain
  values (section 9).

`tests/test_architecture.py` of the package checks the libraries and the
groups. `tests/test_code_rules.py` at the root of the repository checks
the imports of its callers, and that no module of the service or the
MCP server defines one of its functions again.
