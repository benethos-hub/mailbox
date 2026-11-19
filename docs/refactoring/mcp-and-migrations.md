# Refactoring: the MCP server and the migrations

Part of [REFACTORING.md](../REFACTORING.md): sections 10 and 11.

## 10. The MCP server

Concept of 2026-09-28. The MCP package has one module that does four
things, and a client that holds its answers' types beside the requests.

### 10.1 Today

```
benethos_mailbox_mcp/
  server.py      788 lines: the shared REST client, 14 tools and their
                 helpers, the table of tools with their annotations and
                 the choice by rights, the command line
  client.py      594 lines: the requests, and the records it answers
                 with (Me, Folder, Page, Changes, Outcome, Sent,
                 Attachment)
  render.py, pdf.py, transport.py, errors.py
```

A tool and its line in the table stand 400 lines apart: whether a tool
is destructive or idempotent is read far from what it does.

### 10.2 Proposed

**Decided 2026-09-28:** one module per kind of tool, the kinds that
`list_accounts` reports (`read`, `write`, `drafts`, `send`), not one
file per tool. The records of the client go to `models.py`.

```
benethos_mailbox_mcp/
  cli.py         the command line: options, environment, the log, main
  server.py      build_server: the tools the token's rights allow, each
                 logged when it fails, and what the token may do
  tools/
    __init__.py  TOOLS, the catalogue, from the modules below
    base.py      Tool, reads() and changes(), the shared client,
                 result() for text and images
    compose.py   what drafts and sending share: addresses, the message
                 a tool's arguments describe
    accounts.py  list_accounts, which reports the kinds
    reading.py   list_folders, search_messages, get_message, whats_new,
                 get_attachment
    writing.py   update_messages, create_folder
    drafts.py    list_drafts, create_draft, update_draft, delete_draft
    sending.py   send_message, send_draft
  client.py      the requests to the REST API
  models.py      the records the client answers with
  render.py, pdf.py, transport.py, errors.py   as they are
```

Each module of a kind holds its tools and its part of the table, as
`TOOLS`. `tools/__init__.py` joins them. `accounts.py` reads the
modules of the kinds for what each needs, so it imports them and not
the package.

The lines, each module importing only lines below:

```
 cli
 server · transport
 tools
 client · render · pdf
 models · errors
```

Inside `tools`: `accounts`, then `reading · writing · drafts · sending`,
then `compose`, then `base`.

### 10.3 The rules

The rules of ARCHITECTURE.md apply as in the service. The MCP package
gets a `tests/test_architecture.py` of its own: the lines above, the
tools package imported through its `__init__.py` from outside, and one
home per library: `httpx` in `client`, `pypdfium2` in `pdf`, `starlette`
and `uvicorn` in `transport`, the MCP library in `server`, `transport`,
`errors` and `tools/base`. The tests of the tools go to `tests/tools/`.

### 10.4 Order of work

One branch, one commit per step, each passing all checks:

1. This section.
2. `models.py` out of `client.py`.
3. `cli.py` out of `server.py`, the entry point with it.
4. `tools/` out of `server.py`, the tests of the tools to
   `tests/tools/`.
5. The architecture test of the MCP package and ARCHITECTURE.md
   section 3. CLAUDE.md points there already and stays as it is.

The live checks `mcp_stdio.py` and `mcp_http.py` run once at the end.
Nothing a client of the MCP server sees changes: the names of the
tools, their arguments, their descriptions and their annotations stay.

**Built 2026-09-28** on one branch, in this order. The tools a client
sees were compared before and after, as the JSON the server lists, and
are the same. `mcp_stdio.py` and `mcp_http.py` passed at the end.
`tools/base.py` names the result of a tool `ToolResult`, so that the
modules of the kinds need no import of the MCP library. The tests of
every tool are in `tests/tools/`, one file per kind, `test_server.py`
keeps what goes through the server: the choice by rights, the bounds
of the arguments, the start and the log. ARCHITECTURE.md 3 says how a
tool is added.

## 11. The migrations of the schema

Proposal of 2026-10-05. Each step of the schema becomes a class of
one base, so a step describes itself: its number, its statements and
its Python, in one place. The database runs a step without knowing
what is in it. Nothing a user of the service sees changes, and no
migration that shipped changes either: the hashes in `RELEASED` are
the proof.

### 11.1 Today

`migrations/step.py` holds `Migration`, a frozen dataclass of
`statements`, a list of single SQL statements, and `before`, an
optional function that runs first and returns what to log. Each
module `vNNNN_<subject>.py` builds one as the constant `MIGRATION`.
`migrations/__init__.py` imports every module and lists the constants
in `MIGRATIONS` by hand, `SCHEMA_VERSION` is the length of the list.
`Database._migrate` walks the list from the stored version on, a
transaction per step: `before`, the statements, then `meta`.

Three tests hold it together: every statement stands alone, every
module is in the list at its number, found by a scan of the package,
and `RELEASED` keeps a hash of the statements of every migration that
shipped. Two of sixteen steps have Python, 9 and 15, both through
`before`.

What is wrong with it is small. A step's number is not in the step, it
is its place in a list. `before` is a hook on a record, not a method of
a step, so a step with logic reads as data with an attachment. The
hash lives in the tests and not with the thing it hashes.

### 11.2 Proposed

One base class in `migration.py`, the module named as the class,
`step.py` until now:

```python
class Migration(ABC):
    """The step from schema version - 1 to version, in one transaction."""

    version: ClassVar[int]
    statements: ClassVar[tuple[str, ...]]

    def before(self, db: sqlite3.Connection) -> list[str]:
        """Runs first. What to log once the step is committed."""
        return []

    def apply(self, db: sqlite3.Connection) -> list[str]:
        said = self.before(db)
        for statement in self.statements:
            db.execute(statement)
        return said

    @classmethod
    def fingerprint(cls) -> str:
        return hashlib.sha256("\n;\n".join(cls.statements).encode()).hexdigest()
```

`apply` is the template: the same for every step, never overridden.
`before` is overridden by the steps with logic. No `abstractmethod`:
a class without `version` or `statements` fails the tests, which is
soon enough. The class is named as its module, `VNNNN<Subject>`, so the
number stands in the registry too. A module then reads:

```python
class V0009PasswordsUniqueNames(Migration):
    version = 9
    statements = ...

    def before(self, db: sqlite3.Connection) -> list[str]: ...
```

The statements stay byte for byte, so each fingerprint stays, and
`RELEASED` is left as it is. `__init__.py` keeps the registry:

```python
MIGRATIONS: tuple[Migration, ...] = (V0001AccountsUsers(), V0002Credentials(), ...)
SCHEMA_VERSION = MIGRATIONS[-1].version
```

`MigrationRegistry`, in `registry.py`, is what the tuple was: the steps in
order, checked as it is made to be numbered from 1 without a gap. It
knows `schema_version`, gives a `step` by its version and the steps
`pending` for a database at a version, and it owns the table `meta`:
`prepare`, `version_of`, and `apply`, which runs one step and records
its version. `Database._migrate` opens a transaction per pending step
and calls `apply`. The rest of it stays, and `__init__.py` holds the
enumeration alone. The steps move to a package of their own,
`migrations/versions/`, so the base and the registry stand apart from
what is run once and never changes.

The fingerprint covers the statements, not the Python of `before`,
today as after. A hash over source breaks on a comment. That a shipped
step's Python is not touched stays a rule for review, as it is now.

**Superseded 2026-10-07:** the fingerprint is a hash of the step's
whole module, statements, the Python of `before`, its helpers and
comments alike. Migration 15 has no statements, so its fingerprint
of the statements froze nothing. That a shipped step breaks on a
comment is the point: it is never changed.

### 11.3 A registry, not reflection

The list in `__init__.py` stays, written by hand. A scan of the
package (`pkgutil`, `__subclasses__`) would save two lines per
migration and cost more: the order would hang on file names, a typo in
a name would drop a step without a word, mypy and ruff would see the
modules as unused, and the check that the numbers run from 1 to N
without a gap would move from the tests into code that runs at every
start. The test `test_each_migration_module_is_in_the_list_at_its_number`
does that scan already, and the tests are where it belongs. The rule of
[ARCHITECTURE.md](../ARCHITECTURE.md) holds too: an `__init__.py` exports,
it has no side effects.

If the two places per migration, the import and the list, ever
bother: `__init_subclass__` on the base, each class entering itself
into a dict by `version` as it is imported, a second class with the
same number refused at once. The imports in `__init__.py` are then the
registry, the list goes. That is the one piece of reflection worth
having here, and it is not part of this proposal.

### 11.4 Order of work

One branch from `main`, one pull request, each step passing all checks:

1. This section.
2. `migration.py`: the class above, `step.py` renamed.
3. The sixteen modules, by script: `MIGRATION = Migration([...])`
   becomes a class `VNNNN<Subject>` with `version` and `statements` as
   a tuple, the statement texts untouched, 9 and 15 with `before` as a
   method.
   `__init__.py` lists the instances in a `MigrationRegistry`,
   `registry.py`, which owns `meta` and runs a step. The sixteen modules
   move to `versions/`.
   `Database._migrate` asks it for the pending steps and calls `apply`.
4. The tests: `fingerprint` from the class, one test more that
   `version` is the number in the module's name, `RELEASED` as it is.
5. CLAUDE.md's convention and ARCHITECTURE.md's two lines about
   `migrations/` say "a class in a module".

Then once a database file of 0.2.0, schema 13, opened by the service:
the log says it migrated to the current schema, and `live/ui.py` runs
against it. No CHANGELOG entry: the API does not change.
