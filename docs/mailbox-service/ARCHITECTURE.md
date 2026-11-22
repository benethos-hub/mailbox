# Architecture and design rules

Decided 2026-09-28 as a whole. The rules of this service: the layers,
the modules and the seams, where a piece of code goes, how it is
imported, how it is named, and how it is moved.
[CONCEPT.md](CONCEPT.md) says what the service is,
[CLAUDE.md](../../CLAUDE.md) how to work in the repository,
[REFACTORING.md](../REFACTORING.md) how the layout came to be. This file is
the reference: a change that adds a module, a package, a library or a
seam is measured against it.

This file is the overview. It holds the shape, the layers and the guide
to where a piece of code goes. The rest is in
[architecture/](architecture/), under the same section numbers.

## The topics

| Topic | Sections | In short |
|---|---|---|
| [The modules of the service](architecture/modules-service.md) | 3, 3.1 | What each package and module of the service holds, as a tree that a test holds to the disk. |
| [The modules of the client](../mailbox-client/ARCHITECTURE.md) | 3.2 | The same for the client, and what an endpoint of it is. In the folder of its package. |
| [The modules of the MCP server](../mailbox-mcp/ARCHITECTURE.md) | 3.3 | The same for the MCP server, and what a tool of it is. In the folder of its package. |
| [The modules of the common package](../mailbox-common/ARCHITECTURE.md) | 3.4 | The same for `mailbox-common`. In the folder of its package. |
| [The rules](architecture/rules.md) | 5 to 17 | Packages, imports, libraries, the seams that keep parts replaceable, types, errors, state, logging, tests, naming, size and refactoring. |

## Every section

- [1. The shape](#1-the-shape)
- [2. The layers](#2-the-layers)
- [3. The code, module by module](architecture/modules-service.md#3-the-code-module-by-module): [3.1 The service](architecture/modules-service.md#31-the-service) · [3.2 The client](../mailbox-client/ARCHITECTURE.md#32-the-client) · [3.3 The MCP server](../mailbox-mcp/ARCHITECTURE.md#33-the-mcp-server) · [3.4 What the service and the MCP server share](../mailbox-common/ARCHITECTURE.md#34-what-the-service-and-the-mcp-server-share)
- [4. Where does it go?](#4-where-does-it-go)
- [5. Packages](architecture/rules.md#5-packages)
- [6. Imports](architecture/rules.md#6-imports)
- [7. Libraries](architecture/rules.md#7-libraries)
- [8. Encapsulation and replaceable parts](architecture/rules.md#8-encapsulation-and-replaceable-parts)
- [9. Types and values](architecture/rules.md#9-types-and-values)
- [10. Errors](architecture/rules.md#10-errors)
- [11. State and time](architecture/rules.md#11-state-and-time)
- [12. Logging](architecture/rules.md#12-logging)
- [13. Tests](architecture/rules.md#13-tests)
- [14. Naming](architecture/rules.md#14-naming)
- [15. Size](architecture/rules.md#15-size)
- [16. Refactoring](architecture/rules.md#16-refactoring)
- [17. Questions answered](architecture/rules.md#17-questions-answered)

## 1. The shape

Three layers, and imports point down only:

```
 web/      PRESENTATION   HTTP in, HTTP out. Knows who is calling.
 domain/   BUSINESS LOGIC Decides. Knows no HTTP, no SQL, no protocol.
 data/     DATA           Reads and writes. Decides nothing.
```

Beside them, read by every layer and importing none: `config.py`,
`errors.py` and `common/`. Above them, allowed to reach anywhere because
they assemble the service: `assembly/`, `cli/`, `__main__.py`, `logs.py`.
Below all of it, a package of its own: `mailbox-common`, what the
service shares with the MCP server (section 3).

Inside a layer, packages by area (`domain/accounts/`) or by kind
(`data/storage/`). Packages stand in lines, and a package imports only
lines below it. The lines are drawn in section 2.

The tests `tests/test_architecture.py`, `tests/test_packages.py` and
`tests/test_assembly.py` check all of this on every run.
A rule that no test checks is a wish.

## 2. The layers

The three layers and what each may import:

| Layer | Directory | Job | May import |
|---|---|---|---|
| Presentation | `web/` | HTTP: check input, call the domain, answer | domain, data |
| Business logic | `domain/` | decide: accounts, rights, id mapping, sync | data |
| Data | `data/` | own records and foreign mail sources | neither |

- `config.py`, `errors.py` and `common/` are cross-cutting: read by every
  layer, they import none. `assembly/`, `cli/`, `__main__.py` and
  `logs.py` only assemble.
- **`common/` is not a drawer.** A guide, not a rule: it holds helpers
  that know nothing of the domain, the data or the web, with no I/O and
  no state beyond what a caller holds. Mostly what more than one layer
  needs, but a helper of that kind may live there when one layer needs
  it, such as `trim` and `KeyedLocks`. It imports the standard library,
  anyio, idna (host names as IDNA 2008) and `mailbox-common`, nothing
  else. What the MCP server needs as
  well goes to `mailbox-common` (section 3).
- **A helper exists once.** No module outside `common/` defines a
  function of a name `common/` holds, with or without a leading
  underscore. `test_code_rules.py` also names the copies a shared
  helper replaced, with the one module that holds it now, so none comes
  back.
- **No HTTP in the domain.** Nothing below `web/` raises an HTTP exception or
  knows a status code. The domain raises `errors`, and `web/errors.py` maps
  each class to a status.
- **No decisions in the data layer.** It reads and writes, it does not judge.
- **Providers only through the registry.** Outside `data/providers/`,
  nothing imports a provider module, only `data.providers` itself.
- **Two front ends, one domain.** `web/api/` serves the JSON API,
  `web/pages/` the configuration UI. Both call the same domain
  services. Therefore **rights are checked in the domain**, not in a web
  dependency: a check that lives in `routes/` would have to be built a
  second time for `pages/`, and one of the two would drift. The web layer
  only establishes *who* is calling (bearer token for the API, a session
  for the UI) and hands that user to the domain.
- UI pages stay out of the OpenAPI document (`include_in_schema=False`), so
  the contract covers the API only.
- **The domain is in packages by area** (docs/REFACTORING.md 4). Another
  package, the web layer and the assembly import a package through its
  `__init__.py`, from the names in its `__all__`, never a module inside
  it. The activities too: `activity` offers the module of each area,
  `from ..activity import mailbox as said`, then `said.MessageSent(...)`.
  No cycle between packages: what two packages both need goes to the one
  below, or is handed in where the services are wired, as
  `AccountService` gets `on_delete`. The packages and the helper
  modules stand in lines, each importing only lines below:

  ```
   system
   mailbox · users · webhooks
   sync
   accounts
   auth · discovery · changes · rounds
   activity
   rights
   paging
  ```

- **The data layer is in packages by kind**, in the same way: imported
  through the `__init__.py`, no cycle, and lines of its own
  (docs/REFACTORING.md 8.3). `mail` offers its modules:
  `from ..mail import compose`.

  ```
   backup
   secrets
   storage · providers · discovery
   protocols
   mail · files
   models · logbook
  ```
- **The domain logs activities.** A line at `INFO` or above is an
  activity of `domain/activity/catalogue/`, handed to
  `ActivityLog.record`, a sentence as docs/mailbox-service/LOGGING.md section 3 shapes
  it. The data layer logs at `DEBUG` at most: what it notices goes up as
  a result or an error.

`tests/test_architecture.py` checks the direction, the cross-cutting
modules, that `common/` stays on the standard library, anyio, idna (host
names as IDNA 2008) and `mailbox-common`, that FastAPI stays in
`web/` (and `assembly/web.py`), that providers are reached through the registry,
that the domain picks no storage implementation, that SQLite is
reached through `data/storage/` alone, and that the files SQLite keeps
beside a database are named in `data/storage/sqlite/` alone.
`tests/test_code_rules.py`
checks that the data layer logs nothing above `DEBUG` and the domain
nothing but activities, that a broad `except` raises or records, the
sizes of modules and classes, that a helper of `common/` exists
once, that a template asks what the page may do and never the kind
of an account, and that the headers of htmx stand in
`web/pages/templates.py` alone. For the service's own tests it checks
that a test of the data layer goes through no API, that a test of the
domain builds no adapter, and that no test reads `assets/`. The
`tests/test_code_rules.py` at the root of the repository checks that
no `__init__.py` of the four packages defines a class, and how the
others use `mailbox-common`: a module from its group, none of its
functions again and none of its private names. It holds the rules of
section 13 for the tests and the live checks. `tests/test_packages.py` checks that the
packages of the domain and of data are imported through
their `__init__.py`, export what others import, have no cycle, and keep
their lines. `tests/test_assembly.py` checks that nothing below reaches
`assembly/` or `cli/`, that the assembly knows no command, and that the
modules of both keep their lines: in
`assembly/` `web`, `lifecycle`, `domain`, then `storage`, `secrets` and
`providers`, then `services`. In `cli/` each command reaches `common`,
never another command. The client and the MCP server have an
architecture test of their own (section 3).
An import or a line that breaks a rule fails the suite.

## 4. Where does it go?

| I am adding | It goes to |
|---|---|
| a route of the JSON API | `web/api/routes/`, one router per resource, then the OpenAPI document is regenerated |
| a page of the UI | `web/pages/routes/` and a template, after the checklist of UI.md |
| a check of who is calling | `web/api/deps.py` or `web/pages/deps.py`. Nothing else in `web/` decides |
| a decision, a rule, a right | the domain package of its area, in its `service.py` or a module beside it |
| a right | `domain/rights/permissions.py`, the catalogue, then the group that holds it |
| a line for the log | a class in `domain/activity/catalogue/<area>.py`, recorded where the thing happens (LOGGING.md) |
| a change clients hear of | a class in `domain/changes/catalogue.py`, recorded through the feed |
| a type several layers pass around | `data/models/`, one module per subject, pydantic |
| a record the service keeps | its model, a repository protocol in `data/storage/`, the in-memory one beside it, the SQLite one in `data/storage/sqlite/`, and a migration |
| a mail provider | a directory in `data/providers/`, implementing `Reads` and the protocols of `base.py` it can, reached through the registry |
| a wire protocol | a module in `data/protocols/`, one library, in our types. The adapters compose it |
| an autodiscovery source | a module in `data/discovery/`, behind `DiscoverySource`, put in order in `sources.py` |
| a command of the CLI | a module in `cli/` with `add` and `run`, its line in `COMMANDS`. It builds the service through `assembly/` |
| a tool of the MCP server | `tools/<kind>.py` of the MCP package with its line in `TOOLS` there, its request in the client package, its answer a `TypedDict` in `answers.py`, filled by `render.py` (section 3), then `docs/mailbox-mcp/mcp-tools.json` is regenerated and the bundle's manifest names it |
| a request of the Python client | the module of its resource in `endpoints/` of the client package, and one line on each client (section 3) |
| a library | one wrapper module, in the layer that needs it, and nowhere else. The wrapper maps into our types and our errors |
| an error | `errors.py`, a subclass of `MailboxServiceError`. `web/errors.py` gives it a status |
| a setting | `config.py`, as `MAILBOX_SERVICE_<NAME>`, with its default and its line in `.env.example` |
| a helper that knows no layer | `common/`, if it is on the standard library, anyio and idna, does no I/O and holds no state beyond what a caller holds. Else it is not a helper: it belongs to one layer |
| a helper the MCP server needs as well | `mailbox-common`, in the group of its concern (section 3) |
| a helper one layer needs | that layer, beside its caller |

When none of these fits, the seam is missing. Add the seam first, then
the code. A change that has to touch several layers to swap one
technology says the seam is in the wrong place.

