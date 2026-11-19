# Refactoring: the client, mailbox-common and the limits

Part of [REFACTORING.md](../REFACTORING.md): sections 12 to 16.

## 12. The work list of 2026-10

A list of 2026-10-07, after a review of the code and the documents: the
packages first (block 2), then the code inside them (block 3). One pull
request per step, behaviour and the API unchanged unless a step says
so. Built the same day.

### 12.1 Packages and folders

| Step | Pull request | What came of it |
| --- | --- | --- |
| 2.1 | #70 | `packages/mailbox-client`, the client of the REST API as a package of its own: one description per endpoint (`endpoints.py`), `MailboxClient` and `SyncMailboxClient` as thin transports over it. The MCP server is built on it. Decided by the user. |
| 2.2 | #71 | `live/checks/`: what the live checks share, one module per subject. A check reaches mail through the client. |
| 2.3 | #72 | `assembly/` builds the service out of `main.py`, `cli/` holds one module per command. |
| 2.4 | #73 | The schemas of the API split by subject. `openapi.json` unchanged. |
| 2.5 | #74 | Code the adapters wrote three times in one place each. |
| 2.6 | #75 | The mappers of every adapter named alike (ARCHITECTURE 14). |
| 2.7 | #76 | The trees of ARCHITECTURE 3 and CLAUDE.md, the architecture tests for the client, `assembly/` and `cli/`. |

### 12.2 Code

| Step | Pull request | What came of it |
| --- | --- | --- |
| 3.1 | #77 | `MailProvider` split by capability into protocols a provider implements as far as it can. The domain answers `501` for the rest. Decided by the user. |
| 3.2 | #78 | `MailServerAdapter`, the base of IMAP and POP3. The IMAP and JMAP adapters in parts. |
| 3.3 | #79 | JSON from a server read into a shape at the edge (`data/protocols/wire.py`), a body of another shape a `ProviderError`. Decided by the user. |
| 3.4 | #80 | The users service as four: users, roles, tokens, passwords, and their rules. |
| 3.5 | #81 | Long functions in steps. |
| 3.6 | #82 | One translation of errors per protocol (`transport.translated`, `http.refused`). The IMAP session in parts. |
| 3.7 | #83 | Ids, cursors and settings read back into frozen dataclasses with named fields. |
| 3.8 | #84 | `app.state` and `request.state` read with their types in one place each. |
| 3.9 | #85 | The limits below, checked. |

### 12.3 The limits

Decided by the user: hard limits, without exceptions and without
`noqa`. What grows beyond one is split.

- A module at most 500 lines, a class at most 30 methods.
  `test_architecture.py` of the client and of the MCP server and
  `test_code_rules.py` of the service check both.
- A function at most a complexity of 10 (ruff `C901`), 12 branches
  (`PLR0912`) and 50 statements (`PLR0915`).
- Names as pep8-naming has them (ruff `N`): an exception ends in
  `Error`. `formatTime` keeps its name, which `logging.Formatter`
  gives it.

When the limits came in, one module was beyond them:
`domain/mailbox/outgoing.py`, 504 lines. Its checks of a message went
to `checks.py`. On 2026-10-09 the modules near the limit were split
before they reached it (#123): `data/protocols/oauth.py` became a
package, and the services of `auth`, `mailbox` and `accounts` gave
parts to modules of their own.

### 12.4 After the list

What a review of the code after the list found, built the same day,
one pull request each:

| Pull request | What came of it |
| --- | --- |
| #86 | The packaging tests check the three packages alike. |
| #87 | `common/text.py`, `common/urls.py` and `common/retention.py`: text on one line, URLs read one way, one retention for the audits and the change log, purged at start as well. |
| #88 | No `assert` in the code (ruff `S101`), a sign-in with a code that survives an unreachable provider, the MCP server's client made in its lifespan, `from_environment()` in the client, the day filters in local time. |
| #89 | Shared helpers: cursors, the filters of the list pages, canonical JSON, `common/secret.py`. |
| #90 | The MCP server's client reaches its tools on every transport. |
| #91 | A helper of `common/` exists once, checked by the architecture test (ARCHITECTURE 2). |
| #92 | `trim` and `KeyedLocks` in `common/`, which may import anyio since, the size limits for the tests and `live/` too, `test_code_rules.py` apart from `test_architecture.py`. |

## 13. The client in parts

Concept of 2026-10-07, built the same day on one branch, a commit per
step. The package `mailbox-client` came out of step 2.1 with seven
modules side by side. Its interface, the names its `__init__.py`
exports, and what the MCP server and the live checks import stay as
they are. Behaviour and the API stay as they are.

### 13.1 Why

- **`wire.py` held four subjects.** The address and the token with
  their check, the shape of a request and its path, the reading of an
  answer or a failure, and an attachment read in chunks: 288 lines, a
  reader who looks for the URL check finds it beside the charset of
  an attachment. ARCHITECTURE 15: a module holds one subject.
- **`endpoints.py` held every resource.** The caller, folders,
  messages, drafts and sending, and the readings of all their records,
  in one module of 379 lines. The next endpoints the MCP server or a
  script needs, threads, the status, users, take it past 500. The MCP
  server's tools are one module per kind already (section 10), and
  the client that serves them should be cut the same way.
- **The tests followed the modules**, two files for seven modules.

### 13.2 Target

The tree of ARCHITECTURE 3. `endpoints/` becomes a package, one module
per resource of the API as the MCP server's tools are: `accounts`,
`folders`, `messages`, `drafts`, `sending`, `compose` for what drafts
and sending share, `generic` for any route. Each module keeps the
readings of its records, as an adapter keeps its mappers. The page of
summaries is read in `messages` and used by `drafts`. `wire.py` becomes
four modules: `environment` (the address and the token, read or given,
checked), `calls` (the `Call`, its path, the timeouts, the readings
every endpoint may use), `answers` (an answer or a failure read) and
`attachments` (bytes in chunks, what the headers say).

The lines, each importing only lines below, a package as one unit:

```
 client · sync
 endpoints
 answers · attachments · environment
 calls
 models · errors
```

httpx stays where a request is made or read, where an attachment's
headers are read, and where an address is parsed to be checked:
`client`, `sync`, `calls`, `answers`, `attachments`, `environment`.
The endpoints, the records and the errors know no HTTP library. A
module of `endpoints/` is reached from outside through the package
alone, so the package can split or merge its modules.

The tests mirror the modules: `test_environment.py`, `test_calls.py`,
`test_answers.py`, `test_attachments.py`, and `tests/endpoints/` with
one file per module. `fake_api.py` at the top holds the fake API and
the answers the endpoint tests share.

### 13.3 Order of work

1. The new modules, the clients pointed at them, the old two removed,
   the architecture test taught what a package is and that the
   endpoints are reached through theirs. Every test as before.
2. The tests moved into files that mirror the modules, each test as
   it was.
3. The documents: ARCHITECTURE 3, this section, the client's README,
   the roadmap.

Built 2026-10-07, in that order.

## 14. The client's records in parts

Decided by the user on 2026-10-09, as step 0 of the client covering the
whole API.

### 14.1 Why

`models.py` held every record of the client in one file. The client is
to cover the whole API, with records for accounts, users, tokens,
roles, webhooks, the audit and more. One file would pass 500 lines, and
a record would sit far from the endpoints that read it.

### 14.2 Target

`models/` is a package, one module per resource as `endpoints/` is:
`me`, `folders`, `messages`, `sending`, `secrets` and `webhooks`, and a
module of its own for each resource that gets records later. Its
`__init__.py` offers every record, so `from benethos_mailbox_client.models
import Folder` and `from benethos_mailbox_client import Folder` stay as
they are. The package keeps its line, at the bottom beside `errors`.
The tests mirror the modules in `tests/models/` where a record has
behaviour of its own, as `Secret` has.

### 14.3 Order of work

1. The package, the code moved as it was, `models.py` removed, every
   test as before.
2. The documents: ARCHITECTURE 3, this section.

Built 2026-10-09, in that order.

## 15. A fourth package, `mailbox-common`

Decided by the user on 2026-10-09, first as an idea, then to be built.

### 15.1 Why

The MCP server cannot import the service, so what both need was kept
twice: `plaintext.py` as the same file, held equal by a test, the
folders of the operating system, the time and format of a log line,
the canonical JSON of the idempotency key and the size in MiB. The
MCP server's log had neither masking nor colours.

### 15.2 Target

A workspace member `packages/mailbox-common`, on PyPI as
`benethos-mailbox-common` with the version of the others, pinned by the
service and the MCP server. No image: the images of the service and the
MCP server install it with them. It sees neither of them, nor the
client, and imports the standard library and platformdirs alone.
Since 15.4 and 16, platformdirs and pydantic-settings are extras,
`paths` and `settings`, and the package needs the standard library
alone.
Decided with it: platformdirs lives there, and the client does not use
it. Its modules are listed in ARCHITECTURE 3.

The log moved as a whole, as the user decided during the work: the
format, the levels, `log_time`, the plain and the coloured line and a
stderr handler. The service keeps its dictConfig for uvicorn, the log
page and its access line, which it hands the coloured line as
`line_of`. The MCP server keeps stderr alone and the quiet libraries.
So the two logs look alike by construction, and the MCP server notes
its two tokens for masking.

`publish.yml` uploads the packages in the order of their dependencies,
as the user decided: common first, then the client and the service,
then the MCP server. The client waits for common too, so it may come to
need it. `test_publish.py` holds the order to the pyproject files.

### 15.3 Order of work

0. The package, its pins, CI and `publish.yml`.
1. `plaintext`, the copy and the test of equality removed.
2. `system_folders` and `named_file`. Each program keeps its own search
   order, since the service also looks for its data folder in the
   working directory.
3. `redact`.
4. The log.
5. `canonical`, now also the idempotency key of the MCP server.
6. `sizes`.
7. The rule that a function of the package exists once, and the
   documents.

Built 2026-10-09, in that order.

### 15.4 Groups, and three more moves

Decided by the user on 2026-10-10, before the first push of the
package.

- **Groups.** While the package is small, it splits into `mail`, `log`,
  `paths` and `values`, so a group can be cut out as a package of its
  own later. A module imports only inside its group. A group offers its
  modules as namespaces, and a caller imports a module from its group.
  `paths` rather than `system`, since the service has `domain/system/`
  for the running service, and the group is about where files live.
  Not chosen: a namespace package without `__init__.py`, which leaves
  no `__version__` at the root.
- **The rule of two packages.** Only what at least two packages need
  goes in, as a guide (ARCHITECTURE 3).
- **The extra `paths`, as a trial.** platformdirs became an extra named
  after its group, and the package needs the standard library alone.
- **Named records.** `system_folders` returns `SystemFolders`, and
  ARCHITECTURE 9 names the rule for every package boundary.
- **Three more moves.** `addresses.readable` for an address as people
  read it, from four copies in the service and the MCP server. The
  quoted form escapes a quote, which fixes a name read back by the mail
  form. `values/secret.py` from the service, whose `digest` the MCP
  server now uses for its idempotency key. Its bearer compare stays on
  bytes, since a header is bytes a client chooses. `values/text.py`
  from the service, whose `joined` keeps a sender's name, a subject and
  a file name on one line in what the model reads.
- **Left out.** `package_version` in `__init__.py`, which would put
  logic there for four lines per package. The uvicorn start of the
  service and the MCP server, about 15 lines each, until a third server
  appears. httpx, pydantic, anyio and starlette, which the packages use
  differently.

Built 2026-10-10, in that order.

## 16. Records, one settings base, the boundaries

Decided by the user on 2026-10-10, built as #132.

- **Records in the client.** A message is `Message`, a summary
  `MessageSummary`, which `Message` extends, with `Address`,
  `AttachedFile` and `Reference`, where each was a dict. The API's
  `from` is `sender`, a time a `datetime`, `Change.at` too. What a
  call sends stays as it was.
- **One settings base.** pydantic-settings has one home, the group
  `settings` of `mailbox-common` with the extra `settings`, as
  platformdirs has `paths`. `FileSettings` and `load` read the
  environment and a settings file. The service's and the MCP
  server's `Settings` extend it. The MCP server has typed settings
  and no python-dotenv. A settings file no longer changes the
  environment of the process.
- **The boundaries.** `tests/test_boundaries.py`, at the root of the
  repository since #215, checks all four packages: what a package hands on is a named
  record, frozen and with slots, not a tuple or a dict. Each
  exception stands in `ALLOWED` with its reason, and an entry that
  no longer matches fails. The tuples of the domain became
  `IssuedToken`, `OneTimePassword`, `TotpSetup` and `TotpConfirmed`.
