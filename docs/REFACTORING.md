# Refactoring the service

Between 2026-09-28 and 2026-10-10 the code got the layout it has: the
domain and the data layer in packages by area, the tools of the MCP
server in a package, the migrations as classes, and the client and
`mailbox-common` as packages of their own. All of it is built.
Behaviour, the API and the OpenAPI document stayed as they were
throughout.

The rules that came out of it are [ARCHITECTURE.md](mailbox-service/ARCHITECTURE.md),
and the modules as they are now stand in its section 3. This file keeps
what was decided on the way, and the reasons that stand nowhere else.
The sections keep the numbers the code and the other documents name
them by, so some numbers are missing.

## 2. Principles

The principles became rules: [architecture/rules.md](mailbox-service/architecture/rules.md),
sections 5 and 16. One stands only here.

**The same shape for what is alike.** Activities and changes are both
records of something that happened. Both have a catalogue of typed
classes and a recorder, so a reader who knows one knows the other.

## 3. The change feed, shaped like the activities

One module holds the catalogue, `domain/changes/catalogue.py`, not a
folder: there are five kinds. Each kind is a frozen dataclass with its
`kind` as a class variable. The three kinds the feed answers extend
`MessagesChanged`. The base class is `MailboxChange`, not `Change`:
`Change` is the API model in `data/models`.

| Class | `kind`, as the API names it |
|---|---|
| `MessagesCreated` | `message.created` |
| `MessagesUpdated` | `message.updated` |
| `MessagesDeleted` | `message.deleted` |
| `MessageSent` | `message.sent` |
| `AccountNeedsSignIn` | `account.needs_reauth` |

- **Recorded as a class**: `feed.record(MessagesUpdated(account_id,
  ids))`. mypy finds a wrong kind, and no call site writes a name.
- **The names in the API stay**: `kind` is the string the change feed
  and the webhooks answer.
- **The data model has its own names. Decided 2026-09-28:** `Event` in
  `data/models` became `ChangeRecord`, `EventType` became `ChangeKind`.
  `ChangeType` and `CHANGE_TYPES`, the three of the five the feed
  answers, became `FeedKind` and `FEED_KINDS`, so no two names differ by
  Type and Kind alone. Python names are not in the OpenAPI document,
  only the five values under a webhook's `events`, so the contract did
  not move (LOGGING.md 7.1).
- **Activity and change stay apart.** An activity says what was done in
  the service and goes to the log and the audit. A change says what
  changed in a mailbox and goes to clients. Some moments are both: a
  sent mail is `MessageSent` for clients and a send activity for the
  log. The code records both where it happens, each to its own place,
  and they read apart: `said.MessageSent` and `changes.MessageSent`.

## 4. The domain in packages

The packages and their lines are in ARCHITECTURE.md, section 2.

**Decided 2026-09-28:** the package is `mailbox`, after its facade
`MailboxService`. `discovery` is a package of its own: its module was
the largest of the old `accounts` group and knows nothing of accounts.
The module named like its package is `service.py`, so no path stutters
(`auth/auth.py`) and the service of a package is found in the same
place each time. `changes.py` became `changes/feed.py`.

**Decided 2026-09-28:** `Sleep` is the type of a sleep function, two
lines in `worker.py`, and the only thing `delivery.py` took from
`sync`. `delivery.py` declares the alias itself, and `webhooks` does not
import `sync`.

**Decided 2026-09-28:** `accounts` does not import `sync`, which ended a
cycle between the two. `AccountService` takes `on_delete` in its
`AccountHooks`, a callable with the account id, in place of the
`SyncService` it held. The assembly passes one that calls
`sync.forget_account` and the worker's `forget`. `sync` reaches accounts through
`adapters`.

`activity` is imported by every package that records. `rights` records
none, since `activity` imports it. Its one warning, a stored grant that
names unknown rights, is the activity `users.unknown_rights`, recorded
by `auth`. `web/services.py` is the one place of the web layer that
names the services.

## 7. Questions answered

**Decided 2026-09-28:**

- **The package of status, recovery key and log page is `system/`.**
  `service/` would stand beside the `service.py` of most packages. The
  activities it records follow it, `activity.system.*` (LOGGING.md
  7.2). A name has at most 32 characters, so that the longest fits the
  source column of a log line.
- **`data/` got a similar look,** from a concept of its own, section 8.

## 8. The data layer and `common`

**The protocols left the providers. Decided 2026-09-28:**
`providers/protocols/` and `http/` became one package `data/protocols/`,
the wire, one library each, in our types.

**8.3 Inside `data`.** The lines of its packages are in ARCHITECTURE.md,
section 2. What is where, and why:

- `backup` is `data/backup.py`, beside `files.py`. It imports `secrets`
  for the cipher and `storage` for the file, and nothing imports
  `backup` but the command line.
- `sender.py` stays with the providers, since it uses `Guard` and
  `rules`.
- `oauth` is a flow over HTTP rather than a wire protocol. It knows no
  provider, only the endpoints `microsoft/signin.py` and
  `gmail/signin.py` hand it, and is
  under `protocols`.
- Considered for `common` and left in `data`: `logbook.py` is a store of
  log lines the domain reads like a repository. `files.py` is I/O for
  `data` alone. `protocols/http/safe.py` is the network.

**8.4 The rules, as for the domain.** A package of `data` is imported
through its `__init__.py`, from the names in its `__all__`, with no
cycle between packages and in the lines of ARCHITECTURE.md, section 2.
Like `activity`, `mail` exports modules. Tests may import a module
inside a package, since they test it.
`packages/mailbox-service/tests/test_packages.py` runs the same checks
over both layers.

**Decided 2026-09-28 (8.6):**

- The pacing helper keeps its name: `common/ratelimit.py`.
- `logbook` stays in `data`.
- The `Clock` and `Sleep` types stay where they are. They are merged
  into `common/clock.py` when a third user of them appears.

## 9. Code written twice

The code written twice in the domain, the web layer and the data layer
was merged into helpers. A helper new to `common` or the domain gets
its test in the same commit (decided 2026-09-28).

Considered and left: the `rpartition("@")` one-liners, the
case-insensitive substring filter (five places, an idiom),
`quote(safe="")` (one call), and `encode_recovery` (the key's own
format, stays in `data.secrets`).

**9.5 Built otherwise.** Where the code differed from the plan, and
what was accepted. **Decided 2026-09-28:** all of it stays as built.

- The account list keeps a loop of its own, since it filters by two
  rights and three fields more. `Access.filter` serves the rest.
- `if_allowed` is synchronous. The folder list of the mail page is
  awaited and keeps its own check, and `system/status.py` is the domain,
  where the helper does not belong.
- `_loop` in `assembly/lifecycle.py` stays as the guard around a
  background loop that ends for good.
- The time of a log line is `log_time`, as LOGGING.md 6.9 names it, in
  `log/lines.py` of `mailbox-common`.
- The `why()` of the activity catalogue stay, since their reasons
  are of different types.
- The Microsoft adapter keeps its folder roles, which come from Graph's
  well-known names, not from `rules`.
- The method is `MessageFilter.flags_match`, not `matches`, since it
  checks unread, starred and attachments alone.

## 10. The MCP server

**Decided 2026-09-28:** one module per kind of tool, the kinds that
`list_accounts` reports (`read`, `write`, `drafts`, `send`), not one
file per tool. The records of the client go to `models.py`. `share`,
which came later, keeps its tool in `reading.py`.

**10.2 The modules.** Each module of a kind holds its tools and its part
of the table, as `TOOLS`. `tools/__init__.py` joins them. `accounts.py`
reads the modules of the kinds for what each needs, so it imports them
and not the package. `tools/base.py` names the result of a tool
`ToolResult`, so that the modules of the kinds need no import of the MCP
library. The modules as they are: ARCHITECTURE.md 3.3.

**10.3 The rules.** The modules stand in lines, each importing only
lines below (ARCHITECTURE.md 3.3). Inside `tools/` the lines are
`accounts`, then `reading`, `writing`, `drafts`, `sending` and `status`,
then `compose`, then `base`. Each library has its home: the client
package in `client`, `models` and `errors`, `pypdfium2` in `pdf`,
starlette and uvicorn in `transport`, the MCP library in `server`,
`transport`, `listeners`, `errors` and `tools/base.py`. httpx has none:
the server speaks no HTTP to the service itself.
`tests/test_architecture.py` of the package holds all of it.
`test_server.py` keeps what goes through the server: the choice by
rights, the bounds of the arguments, the start and the log.

## 11. The migrations of the schema

Of 2026-10-05. Each step of the schema is a class of one base. How a
new one is written: [the service's CLAUDE.md](../packages/mailbox-service/CLAUDE.md).

- **`Migration`**, in `migration.py`, has a `version`, its `statements`
  and `before` for a step in Python. `apply` is the template: the same
  for every step, never overridden. There is no `abstractmethod`: a
  class without `version` or `statements` fails the tests, which is soon
  enough. The class is named as its module, `VNNNN<Subject>`.
- **`MigrationRegistry`**, in `registry.py`, holds the steps in order,
  checked as it is made to be numbered from 1 without a gap. It knows
  `schema_version`, gives a `step` by its version and the steps
  `pending` for a database at a version, and it owns the table `meta`:
  `prepare`, `version_of`, and `apply`, which runs one step and records
  its version. The steps are a package of their own,
  `migrations/versions/`, so the base and the registry stand apart from
  what is run once and never changes.
- **The fingerprint, since 2026-10-07,** is a hash of the step's whole
  module: statements, the Python of `before`, its helpers and comments
  alike. Migration 15 has no statements, so a fingerprint of the
  statements froze nothing. That a shipped step breaks on a comment is
  the point: it is never changed.

**11.3 A registry, not reflection.** The list in `__init__.py` is
written by hand. A scan of the package (`pkgutil`, `__subclasses__`)
would save two lines per migration and cost more: the order would hang
on file names, a typo in a name would drop a step without a word, mypy
and ruff would see the modules as unused, and the check that the
numbers run from 1 to N without a gap would move from the tests into
code that runs at every start. The test
`test_each_migration_module_is_in_the_list_at_its_number` does that
scan already, and the tests are where it belongs. The rule of
ARCHITECTURE.md holds too: an `__init__.py` exports, it has no side
effects.

If the two places per migration, the import and the list, ever bother:
`__init_subclass__` on the base, each class entering itself into a dict
by `version` as it is imported, a second class with the same number
refused at once. That is the one piece of reflection worth having here.
It is not built.

## 15. A fourth package, `mailbox-common`

Decided 2026-10-09: what the service and the MCP server
both need is a package of its own, `benethos-mailbox-common` on PyPI,
with the version of the others, pinned by the service and the MCP
server. It has no image: the images of the service and the MCP server
install it with them. It sees neither of them, nor the client.

- It needs the standard library alone. platformdirs and
  pydantic-settings are extras, `paths` and `settings`. The client does
  not use platformdirs.
- The log moved as a whole: the
  format, the levels, `log_time`, the plain and the coloured line and a
  stderr handler. The service keeps its dictConfig for uvicorn, the log
  page and its access line. The MCP server keeps stderr alone and the
  quiet libraries. So the two logs look alike by construction.
- `publish.yml` uploads the packages in the order of their
  dependencies: common first, then the client and
  the service, then the MCP server and the agents. `test_publish.py` holds the order
  to the pyproject files.
- Each program keeps its own search order for its folders, since the
  service also looks for its data folder in the working directory.

**15.4 Groups, and three more moves.** Decided
2026-10-10, before the first push of the package.

- **Groups.** While the package is small, it splits into `mail`, `log`,
  `paths` and `values`, so a group can be cut out as a package of its
  own later. `settings` joined them with section 16. A module imports
  only inside its group. A group offers its modules as namespaces, and a
  caller imports a module from its group. `paths` rather than `system`,
  since the service has `domain/system/` for the running service, and
  the group is about where files live. Not chosen: a namespace package
  without `__init__.py`, which leaves no `__version__` at the root.
- **The rule of two packages.** Only what at least two packages need
  goes in, as a guide (ARCHITECTURE.md 3.4).
- **The extra `paths`.** platformdirs is an extra named after its
  group.
- **Named records.** `system_folders` returns `SystemFolders`, and
  [architecture/rules.md](mailbox-service/architecture/rules.md) section 9 names the
  rule for every package boundary.
- **Three more moves.** `addresses.readable` for an address as people
  read it, from four copies in the service and the MCP server.
  `values/secret.py` from the service, whose `digest` the MCP server
  uses for its idempotency key. Its bearer compare stays on bytes,
  since a header is bytes a client chooses. `values/text.py` from the
  service, whose `joined` keeps a sender's name, a subject and a file
  name on one line in what the model reads.
- **Left out.** `package_version` in `__init__.py`, which would put
  logic there for four lines per package. The uvicorn start of the
  service and the MCP server, about 15 lines each, until a third server
  appears. httpx, pydantic, anyio and starlette, which the packages use
  differently.

## 16. Records, one settings base, the boundaries

Decided 2026-10-10.

- **Records in the client.** A message is `Message`, a summary
  `MessageSummary`, which `Message` extends, with `Address`,
  `AttachedFile` and `Reference`. The API's `from` is `sender`, and a
  time is a `datetime`.
- **One settings base.** pydantic-settings has one home, the group
  `settings` of `mailbox-common` with the extra `settings`, as
  platformdirs has `paths`. `FileSettings` and `load` read the
  environment and a settings file. The service's, the MCP server's and
  the agents' `Settings` extend it. A settings file does not change the environment
  of the process.
- **The boundaries.** `tests/test_boundaries.py`, at the root of the
  repository, checks all five packages: what a package hands on is a
  named record, frozen and with slots, not a tuple or a dict. Each
  exception stands in `ALLOWED` with its reason, and an entry that no
  longer matches fails. The tuples of the domain became `IssuedToken`,
  `OneTimePassword`, `TotpSetup` and `DeviceAdded`.

## 17. The storage layer in `mailbox-common`

On 2026-11-27 the layer beneath the repositories of the service moved
into the group `storage` of `mailbox-common`, so the agents can stand
on it too. The service keeps what is its own: its tables, its
repositories, its revisions and the old steps of its file. What moved
knows no program by name. It is handed a `Shape`, the description of a
program's database, which the service builds at one place. The group
raises its own errors, or the subclasses a program hands in, so every
`except` and the status table of the service stayed as they were. A
group of `mailbox-common` imports only inside itself, so the helpers
the layer needs moved with it: the times as text, the plain names, the
files for their owner alone and the lock of one writer, which the
service now takes from there. Nothing a user or an operator sees
changed: the key of the lock on a server, the row that keeps it and
every text the service says.
