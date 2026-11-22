# Concept of the MCP server

The MCP server, `mailbox-mcp`: section 8 of the
[concept](../mailbox-service/CONCEPT.md), which holds the overview and
every other section. Its client, section 8.2, is in
[mailbox-client](../mailbox-client/CONCEPT.md).

## 8. MCP server

Its own package, `mailbox-mcp` (`benethos-mailbox-mcp` on PyPI), in the same uv workspace
as the service (**decided 2026-09-24**). It depends on `mcp` and the
Python client `mailbox-client` (8.2), `mailbox-common`, which it shares
with the service and through which it reads its settings, `pypdfium2`
for PDF pages, `typing-extensions` for the types of its answers, and
`uvicorn`, `starlette`, `anyio` and `pydantic`, which
`mcp` brings too. It never depends on the service package or a mail library,
so `uvx benethos-mailbox-mcp` stays small and the REST-only rule is
enforced by the dependency list itself. A test checks that no module
imports the service.

It calls the REST API through the client, with the
`MAILBOX_SERVICE_URL` and `MAILBOX_SERVICE_TOKEN` of its settings. The URL is `https`, or `http` to this machine only, since the token
goes with every request. `MAILBOX_SERVICE_ALLOW_HTTP=1` allows `http` to
another host, e.g. between containers (**decided 2026-09-27**). A URL
with a user or password is refused: the address is named in the error
when the service cannot be reached, which reaches the model. It runs over stdio or streamable HTTP. Over HTTP a bearer guard
admits clients with one shared token (`MAILBOX_MCP_BEARER_TOKEN`), which
is not passed on: the server acts as the user of its own API token, for
every client alike. Host and Origin are checked against DNS rebinding.
On an address other hosts reach, such as `0.0.0.0`, it does not start
without the bearer token and a list of allowed hosts or origins
(**decided 2026-11-10**). A catalogue starts without them, since it
runs no tool but `server_status`. At
start it asks `/v1/me` what its user may do, and only those tools exist.
It asks again while it runs and tells its clients when they change
(7.5).

Tools are hand-written, not generated from OpenAPI: generated tools mirror
every parameter and cost far more context than they give. Each tool maps onto
one or two `operationId`s.

| Tool | Access | REST |
|---|---|---|
| `list_accounts` | any token | `get_me` |
| `list_folders` | read | `list_folders` |
| `search_messages` | read | `list_all_messages` across accounts, or `list_messages` for one |
| `get_message` | read | `get_message`, body shortened, `max_chars` param |
| `get_thread` | read | `get_thread`, then `get_message` for the newest 20 mails: a conversation as text, from a mail of it or its thread id (6.3) |
| `get_attachment` | read | `get_attachment`: images as images, PDF pages as images, text types as text, other types by name only |
| `share_attachment` | share | `share_attachment`: a link to an attachment for another service, which fetches the file itself (6.3) |
| `whats_new` | read | `list_all_changes` across accounts, or `list_changes` for one, the "what came in since" tool |
| `update_messages` | write | `batch_messages`: mark read, star, move (not into the drafts folder), archive, trash, add and take off keywords and labels |
| `create_folder` | write | `create_folder` |
| `update_folder` | write | `update_folder`: rename or move. Deleting a folder stays out of the tools |
| `list_drafts` | drafts | `list_drafts` |
| `create_draft` | drafts | `create_draft`, incl. reply / forward by reference, with or without the quote, a forward inline or as a file, `reply_to`, attachments as base64 and of other mail |
| `update_draft` | drafts | `update_draft`, replaces the whole draft |
| `delete_draft` | drafts | `delete_draft` |
| `send_message` | send | `send_message`, with an idempotency key derived from the call |
| `send_draft` | send | `send_draft`, with an idempotency key derived from the call |
| `server_status` | always | none: what the server knows, from its own calls of `health` and `get_me` |

**Decided 2026-09-24, attachments:** `get_attachment` hands images over
as images, the pages of a PDF as PNG images (a page range, a few pages at
a time), text types as text inside the foreign-content marker, and other
types by name, type and size only. An HTML attachment becomes text as an
HTML body does, its hidden parts left out. The conversion happens in the MCP
server. The API keeps handing out the attachment as it is. A PDF sent as
an embedded resource was refused by claude.ai in a test: it takes such a
blob for an image.

**Decided 2026-09-24:** sending a new mail and sending a draft are two
tools, `send_message` and `send_draft`. The model may create folders
(`create_folder`). Text from PDF attachments comes later.

**Decided 2026-09-25:** no policy file. The token's rights, its grants and
their constraints decide which tools exist. The idea waits in IDEAS.md.

**Decided 2026-11-09, the catalogue:** a directory such as Glama starts
the server in a sandbox without a service or a token and reads its tool
list there. For that, `MAILBOX_MCP_CATALOGUE=true` lists every tool and
runs none but `server_status`, which answers as usual. It is set only
where a directory builds the server, never by default: a server with a
token keeps to the token's rights unchanged, and a token beside the
catalogue stops the start.

`benethos-mailbox-mcp --list-tools` prints the tools as a client lists
them, as JSON, without starting a server. `docs/mailbox-mcp/mcp-tools.json` holds
that list, and a test compares it with the code.

Principles:

- The **rights of the token** decide which tools exist (`/v1/me`).
  Whether the model may send or only draft is the operator's choice, both
  are supported equally (7.7).
- Mail content in tool output is marked as foreign content (7.7).
- Descriptions under 700 characters, compact output (no headers the model
  does not need, bodies truncated, HTML converted to text).
- Every error surfaces as an MCP `ToolError` with the REST error message.

**Decided 2026-10-10, how a client finds it:** the MCP server is listed
in the official MCP Registry as `io.github.benethos-hub/benethos-mailbox-mcp`
with two packages, the PyPI package started with `uvx` and a Claude
Desktop extension, `benethos-mailbox-mcp.mcpb`, which every release
carries. The extension pins the PyPI package of the same version and
Claude Desktop installs it with uv and Python of its own. Both ask for
`MAILBOX_SERVICE_TOKEN` alone, and take `MAILBOX_SERVICE_URL` (default
`http://127.0.0.1:8080`) and `MAILBOX_SERVICE_ALLOW_HTTP` if set. The
bearer token of the HTTP transport stays out, since a client starts the
server over stdio, and the image is not in the entry. The package
description is one sentence of at most 100 characters, the same on PyPI
and in the entry. The entry and the manifest of the extension live in
`.github/publish/`, each held by a test, and `publish.yml` builds the
extension after the PyPI upload and publishes the entry last.

### 8.1 Operation

**Decided 2026-09-24:** two processes with different lifetimes.

```
 Claude Desktop / Claude Code          (spawns on demand, one per client)
   └─ benethos-mailbox-mcp          stdio, short-lived, stateless
          │ HTTP 127.0.0.1:8080, bearer token
 benethos-mailbox-service serve             permanent service
   ├─ REST API
   ├─ background worker (sync, IDLE, change feed, webhooks)
   └─ SQLite: accounts, credentials, id mapping, sync state
```

- **The MCP server runs on demand:** a client spawns it over stdio, and it
  ends with the client. Streamable HTTP stays available
  for clients that connect to a URL instead.
- **The REST server runs permanently.** As a container (compose, bound to
  the loopback address) or as a background service on the host (`serve`,
  started at login).

**Decided 2026-09-24, container:** the image is built by GitHub Actions for
`linux/amd64` and `linux/arm64` and pushed to the GitHub container
registry. The master key reaches the container as a file secret.
**Decided 2026-10-06:** `containers/images/` holds the image folders, and
each place they run in has a folder of its own beside it, with its own
`secrets/`: `production/`, `development/` (the name decided 2026-10-08),
which builds from the repository, and `test-mail-server/`, Stalwart for
tests.

**Decided 2026-10-06, operation:** `containers/production/mailbox-service/` runs the
published images without a clone of the repository. `.env` names a fixed
version, and an update changes it. Its `compose.yaml` holds no MCP server:
it acts as one user with that user's token, so each client starts one
of its own, an instance per client, against the service's address.
With the profile `https`, Caddy stands in front, gets a
certificate from Let's Encrypt and is the one container that listens on
every address, on 80 and 443. The service believes the forwarded headers
of Caddy's fixed address alone. The first start is `setup.sh` there, or
the same steps by hand from its README. The project name stays
`benethos-mailbox`, so the volume of the compose file before stays.

**Decided 2026-10-06, MCP server instances and certificates:** for a
client that connects over HTTP, MCP server instances may run beside the
service, never by default. Each is a service of
`compose.override.yaml` that extends the template `mcp.yaml`, with the
profile `mcp`, one user's token and a bearer token of its own in
`secrets/mcp/`. A port on `127.0.0.1` serves a client on the host. A
route in Caddy, one file per instance in `caddy.d/` under a path of its
own, serves clients elsewhere. An instance may also run on another host
against the service's https address. No script adds instances, the
README has the steps. `MAILBOX_TLS` says where Caddy's certificate comes
from: `acme` (Let's Encrypt), `internal` (Caddy's CA) or `files` (one of
your own, e.g. a company CA), so Caddy also serves a network without
access from the internet. A certificate by DNS challenge, which needs a
Caddy image of its own, is left out.

Rules of the implementation (phase 3): the image holds the service package
and the common package only, installed from the lockfile, and runs as a non-root user on a
read-only root file system. Configuration comes from the environment, the
database from the volume `/data`. `keys generate` prints a new master key
for the secret file, and `keys init` then adds the data key. The compose
file publishes the port on `127.0.0.1` only. See the "Container" sections
of the package READMEs.

Why the REST server cannot be spawned per session like an MCP server:

1. **Background fetching.** New mail, the change feed, `whats_new` and
   webhooks need something that watches the mailboxes while no client is
   open: IMAP IDLE or polling, Gmail `history.list`, Graph delta queries.
2. **Connection limits.** Providers limit simultaneous IMAP connections per
   account. Every open Claude window spawns its own stdio process, so
   connections per process would multiply. One service owns one connection
   per account and all clients share it.
3. **Cost per login.** An IMAP login with TLS takes seconds. A permanent
   service logs in once and keeps the session.
4. **OAuth callbacks** for Gmail and Microsoft need a server that is
   listening when the browser redirects back.
5. **Shared state.** Id mapping, idempotency keys and sync state belong to
   one owner, not to several short-lived processes.

What the worker does and does not do: it keeps sync state, the id mapping
(4.1) and the change feed current.

**Decided 2026-09-24:** the worker watches the inbox of an IMAP account
over IDLE and polls the other folders, every 5 minutes by default,
configurable. A JMAP account is watched through the event source of its
server instead. A poll asks each folder for its state and reads only the
folders whose state changed. It does **not** mirror mailboxes. List, search
and get still go to the provider live, unless the local cache of open
question 5 is decided.

A Microsoft account keeps no id mapping. At the same interval the worker
asks each of its folders with a Graph delta query what changed since the
last pass. A message that left one folder and came into another moved.
One that is new to a folder counts as created when Graph dates its
creation after the last pass, else as updated. A message that arrives
while a pass runs may therefore count as updated.

A provider can forget the token of the last pass: Graph and Gmail after
a while, a JMAP server when it keeps no more changes. The folder is then
read whole, and the messages that arrived since the last pass count as
created: Graph dates each, Gmail and JMAP are asked for those received
since then. The rest is known already. What was deleted in the gap is
not reported.

**Without a network hop**, for live checks only: `live/common/service.py`
runs the service app in the script's own process and carries the
requests of the Python client into it through Starlette's test client.
The REST contract stays the same. The MCP server's tests mock the REST
API instead, and its live checks start a service as a process. None of
this is offered as a user mode, since it would put the service package
into the MCP installation.
