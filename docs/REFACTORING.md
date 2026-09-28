# Refactoring the service

Proposal of 2026-09-28, in two parts. Sections 1 to 7 are the domain:
it had grown to 27 modules side by side in one folder, and got packages
by area, and a shape for the change feed like the one
[LOGGING.md](LOGGING.md) section 7 gives the activities. Section 8 is
the data layer and `common`, the same rules applied there. Nothing
changes in behaviour: modules move, names get clearer, the API and the
OpenAPI document stay as they are. The rules that came out of it, in
short, are [ARCHITECTURE.md](ARCHITECTURE.md). What the user decides is
marked as decided, everything else is the proposal.

**Built 2026-09-28**, steps 2 to 5 of section 6. Sections 1 and 3.1
describe the domain before. Section 8 is not built.

## 1. Why

- **Flat.** `domain/` holds 27 modules beside its `__init__.py`, from 17
  to 500 lines. A reader
  who looks for sending finds `outgoing.py`, `sending.py`,
  `idempotency.py`, `replies.py` and `calls.py` between `auth.py` and
  `worker.py`, with nothing that says they belong together.
- **The layout does not show the seams.** CLAUDE.md lists every module
  with one line. What a module is part of is left to the reader.
- **The change feed is written with strings.** `"message.updated"` and
  its kind are typed as literals where a change is recorded, in
  `calls.py`, `outgoing.py`, `adapters.py` and `sync.py`. The data model
  behind it is called `Event`, a word LOGGING.md 7.1 keeps free.
- **One cycle between areas.** `accounts.py` imports `sync.py` to forget
  an account's sync state on delete, and `sync.py` reaches the accounts
  through `adapters.py`. Modules have no cycle, the areas they belong to
  would.

## 2. Principles

1. **Move, do not change.** Each step moves modules and fixes imports.
   Behaviour, the API and the OpenAPI document stay the same. The tests
   stay green at every commit and change only their imports.
2. **One package per area**, named for what it is about, not for a
   pattern. Its `__init__.py` exports what other packages and the web
   layer use. The rest is the package's own.
3. **Other packages import a package through its `__init__.py`**, never
   a module inside it. So a package can split or merge its modules
   without its callers noticing. A test checks it.
4. **No cycle between packages.** A test checks it, as
   `test_architecture.py` checks the layers today.
5. **The same shape for what is alike.** Activities and changes are both
   records of something that happened. Both get a catalogue of typed
   classes and a recorder, so a reader who knows one knows the other.

## 3. The change feed, shaped like the activities

### 3.1 Today

- `domain/changes.py` holds `ChangeFeed`: record, page, the current
  point, purge, forget an account.
- `data/models/changes.py` holds `EventType`, a literal of five names,
  `Event`, one record of the feed, and `ChangeType`, the three of the
  five the change feed answers. `Change` and `ChangePage` are what the
  API answers. A webhook's `events` is a list of `EventType`, so the
  five values are in the OpenAPI document, under that field.
- A change is recorded as `feed.record(account_id, "message.updated",
  ids)` or through `sync.changed(...)` and `calls.changed(...)`, the
  name a string at each call.
- `domain/delivery.py` reads the feed for the webhooks.

### 3.2 Proposed

```
domain/
  changes/
    __init__.py      ChangeFeed, MailboxChange and its classes: what
                       others use
    catalogue.py     one frozen class per kind of change
    feed.py          ChangeFeed: record, page, the current point, purge
```

One module holds the catalogue, not a folder: there are five kinds, not
sixty.

```python
@dataclass(frozen=True)
class MessagesUpdated(MailboxChange):
    kind: ClassVar[str] = "message.updated"  # the name in the API, unchanged
    account_id: str
    message_ids: list[str]
```

The base class is `MailboxChange`, not `Change`: `Change` is the API
model in `data/models`, and `domain/changes.py` imports it today.

| Class | `kind`, as the API names it |
|---|---|
| `MessagesCreated` | `message.created` |
| `MessagesUpdated` | `message.updated` |
| `MessagesDeleted` | `message.deleted` |
| `MessageSent` | `message.sent` |
| `AccountNeedsSignIn` | `account.needs_reauth` |

- **Recorded as a class**: `feed.record(MessagesUpdated(account_id,
  ids))`. mypy finds a wrong kind, and no call site writes a name.
  `SyncService.changed` and `Calls.changed`, which pass a name on
  today, take the class as well.
- **The names in the API stay**: `kind` is the string the change feed
  and the webhooks answer today.
- **The data model gets its own name. Decided 2026-09-28:** `Event` in
  `data/models` becomes `ChangeRecord`, `EventType` becomes
  `ChangeKind`. `ChangeType` and `CHANGE_TYPES`, the three of the five
  the feed answers, become `FeedKind` and `FEED_KINDS`, so no two names
  differ by Type and Kind alone. Python names are not in the OpenAPI
  document, only the five values under a webhook's `events`, so the
  contract does not move (LOGGING.md 7.1).
- **Activity and change stay apart.** An activity says what was done in
  the service and goes to the log and the audit. A change says what
  changed in a mailbox and goes to clients. Some moments are both: a
  sent mail is `MessageSent` for clients and a send activity for the
  log. The code records both where it happens, each to its own place.

## 4. The domain in packages

| Package | Modules today | What it is about |
|---|---|---|
| `rights/` | `access.py`, `permissions.py` | who may do what: the catalogue of rights, `Access` |
| `auth/` | `auth.py`, `passwords.py`, `throttle.py` | proving who calls: tokens, passwords, the sign-in brake |
| `users/` | `users.py` | users, roles, tokens as records |
| `accounts/` | `accounts.py`, `adapters.py`, `oauth.py` | mail accounts: connect, change, the live adapter, OAuth |
| `discovery/` | `discovery.py` | autodiscovery: trust, ranking, cache, limits |
| `mailbox/` | `mailbox.py`, `calls.py`, `merge.py`, `replies.py`, `outgoing.py`, `sending.py`, `idempotency.py` | reading, changing and sending mail, drafts, lists across accounts, the grant limits and the audit of sends |
| `sync/` | `sync.py`, `worker.py` | the id mapping, the sync pass, polling and IDLE |
| `changes/` | `changes.py` | the change feed (section 3) |
| `webhooks/` | `webhooks.py`, `delivery.py` | webhooks and their posts |
| `activity/` | built, LOGGING.md steps 2 to 5 | the activities of LOGGING.md section 7. The areas of its catalogue are the packages of this table, and a move keeps every activity's name (LOGGING.md 7.2) |
| `system/` | `status.py`, `recovery.py`, `servicelog.py` | the service at a glance: status, recovery key, log page |
| (top level) | `locks.py`, `paging.py` | helpers several packages share |

```
domain/
  __init__.py
  locks.py, paging.py
  rights/       access.py, permissions.py
  auth/         service.py, passwords.py, throttle.py
  users/        service.py
  accounts/     service.py, adapters.py, oauth.py
  discovery/    service.py
  mailbox/      service.py, calls.py, merge.py, replies.py,
                outgoing.py, sending.py, idempotency.py
  sync/         service.py, worker.py
  changes/      feed.py, catalogue.py
  webhooks/     service.py, delivery.py
  activity/     base.py, recorder.py, catalogue/
  system/       status.py, recovery.py, servicelog.py
```

**Decided 2026-09-28:** the package is `mailbox`, after its facade
`MailboxService`. `discovery` is a package of its own: its module is the
largest of the old `accounts` group and knows nothing of accounts. The
module named like its package becomes `service.py`, so no path stutters
(`auth/auth.py`) and the service of a package is found in the same
place each time. `changes.py` becomes `changes/feed.py`. The other
modules keep their names.

Sending stays in `mailbox/`, not in a package of its own:
`MailboxService` holds the sending as `mailbox.outgoing`, and sending
builds on the calls of `calls.py`. Two packages would import each other.

### 4.1 The direction between packages

What each package imports, besides `activity` and the helpers
`locks.py` and `paging.py`:

| Package | Imports |
|---|---|
| `rights` | nothing |
| `activity` | `rights` |
| `changes` | nothing but `activity` |
| `auth` | `rights` |
| `discovery` | `rights` |
| `accounts` | `rights`, `changes` |
| `users` | `rights`, `auth`, `accounts` |
| `sync` | `accounts` (the adapters), `changes` |
| `mailbox` | `rights`, `accounts`, `sync`, `changes` (the classes at the call sites) |
| `webhooks` | `rights`, `changes` |
| `system` | `rights`, `auth`, `accounts`, `sync`, `webhooks` |

So the packages stand in lines, each importing only lines below
([CONCEPT.md](CONCEPT.md) 1.1):

```
 system
 mailbox · users · webhooks
 sync
 accounts
 auth · discovery · changes
 activity
 rights
```

`activity` is imported by every package that records. `rights`
records none, since `activity` imports it: its one warning, a stored
grant that names unknown rights, stays a plain log line.

**Decided 2026-09-28:** `Sleep` is the type of a sleep function, two
lines in `worker.py`, and the only thing `delivery.py` takes from
`sync`. `delivery.py` declares the alias itself, and `webhooks` stops
importing `sync`.

**Decided 2026-09-28:** the cycle of section 1 goes: `accounts` no
longer imports `sync`. `AccountService` takes `on_delete`, a callable
with the account id, in place of the optional `SyncService` it holds
today, and `build_services` passes `sync.forget_account`, as the other
pieces are wired there. `sync` reaches accounts through `adapters`, as
it does today.

## 5. What else changes

- **CLAUDE.md** lists the packages with one line each, not every module.
  The module docstrings say the rest.
- **`test_architecture.py`** gets the rules of section 2: imports
  between packages through `__init__.py`, of names in its `__all__`, no
  cycle between packages. Without an exception: `activity` offers the
  module of each area of its catalogue in its `__init__.py`, and a
  package imports its area through it, `from ..activity import mailbox
  as said`, then records `said.MessageSent(...)`. So the activity and
  the change of a sent mail read apart, `said.MessageSent` and
  `changes.MessageSent`.
- **The web layer and `main.py`** import through the packages'
  `__init__.py` as the packages do: `from ..domain.accounts import
  AccountService`. So a package exports what the assembly wires as
  well, `Adapters`, `SyncWorker`, `WebhookDispatcher`. `web/services.py`
  stays the one place that names the services. Routes and pages import
  `Access` and the types they use the same way, in a dozen places
  today.
- **The tests** may import a module inside a package, since they test
  that module. They are in folders like the source since the move
  (section 7): `tests/domain/<package>/`, `tests/data/`, `tests/web/`,
  and `tests/integration/` for a test of several layers at once.

## 6. Order of work

1. This file, one pull request of documentation.
2. The change feed of section 3: the catalogue, the classes at each call
   site, `ChangeRecord`, `ChangeKind` and `FeedKind` in the data layer.
   Small, and it shows the shape before the move. The package
   `changes/` comes with it, as the catalogue needs a home.
3. The packages of section 4, one commit per package, the leaves first:
   `rights`, `changes`, `auth`, `discovery`, then `accounts` with the
   cycle removed, `users`, `sync`, `mailbox`, `webhooks`, `system`.
4. The architecture tests of section 5 and CLAUDE.md.
5. The tests in folders like the packages (section 7), moved, not
   changed.
6. `activity/` is built already, in its place. A move of the other
   packages leaves the areas and names of the activities as they are.

Steps 2 to 5 are one branch, one commit per step, and in step 3 one
commit per package. Each commit passes all checks. The live checks run
once at the end, since nothing they see changes.

## 7. Questions answered

**Decided 2026-09-28:**

- **The package of status, recovery key and log page is `system/`.**
  `service/` would stand beside the `service.py` of most packages. The
  activities it records follow it, from `activity.service.*` to
  `activity.system.*` (LOGGING.md 7.2). No release has the old names.
  An area has at most seven letters, so that the longest name,
  `activity.system.backup_restored`, fits the source column of 32.
- **The tests mirror the packages,** in the same branch, after the
  domain has moved (step 5 of section 6). They move and change their
  imports, nothing else.
- **`data/` gets a similar look,** from a concept of its own and in a
  branch of its own, not in this one.

## 8. The data layer and `common`

Proposal of 2026-09-28, the second part. `data/` is in packages by kind
already, so it does not move as a whole. This part applies the rules of
section 2 to it, takes two modules of a global nature out of it into
`common/`, and names what else is out of place. Nothing changes in
behaviour.

### 8.1 Today

```
data/
  files.py       files for the owner alone (0600), the lock file
  logbook.py     the newest log lines in memory, for the log page
  models/        provider-neutral types, one module per subject
  mail/          messages in RFC 5322: compose, parse, convert, text, fields
  http/          httpx: base, safe (the SSRF guard), api, post
  storage/       the repository protocols, in memory, sqlite/ (migrations/)
  secrets/       cipher, keys, passwords, vault, redact, backup
  providers/     base, rules, guard, ratelimit, sender, protocols/,
                 imap/, memory/, microsoft/
  discovery/     base, presets, isp, ispdb, mx, autoconfig, dns, suffix,
                 placeholders
common/
  clock.py, ids.py, opaque.py
```

What each package of `data` imports of the others, from the modules'
imports today:

| Package | Imports |
|---|---|
| `models`, `files`, `http` | nothing |
| `mail` | `models` |
| `storage` | `models`, `files` |
| `secrets` | `models`, `files`, `storage` (the vault's repositories, the backup) |
| `logbook` | `secrets` (`redact` alone) |
| `providers` | `models`, `mail`, `http`, `secrets` (`redact` alone) |
| `discovery` | `models`, `http` |

No cycle. Three things stand out:

- **`redact` is read by every layer.** `logs.py`, the web layer in three
  places, the domain in two, and inside `data` the logbook, the vault
  and the OAuth wrapper. It is a helper of the whole service that sits in
  `data/secrets/` by its history. Worse, `from ...secrets import redact`
  imports the package, and with it the vault, the storage protocols and
  SQLite: the providers depend on the database for a masking function.
- **`ratelimit` is read by the domain.** The worker takes `backoff`
  through `data.providers`. A token bucket and a backoff are pacing
  helpers on the standard library, not data access.
- **`backup` sits in `secrets`.** It encrypts, but it is the one module
  of `secrets` that reads the database file, and half of why `secrets`
  imports `storage`.

Seven imports reach inside a package instead of its `__init__.py`:
`data.secrets.redact` four times, `data.models.messages` for
`SEARCH_TEXT_PATTERN`, `data.models.webhooks` for `CHANGE_KINDS`,
`data.mail.text` for `from_html`. Inside `data`, `storage` reaches
`models.changes` and `models.webhooks`, `providers` reaches `mail.parse`
and `mail.fields`. And three `__init__.py` do more than export:
`storage/__init__.py` (217 lines) holds `Store`, `Repositories` and
`open_repositories`, `providers/__init__.py` (193 lines) the registry
with `build_provider`, `sign_in`, `probe_server` and the settings
helpers, `discovery/__init__.py` `default_sources` and `preset_hosts`.

### 8.2 To `common`

| Module | From | Why |
|---|---|---|
| `common/redact.py` | `data/secrets/redact.py` | read by every layer, standard library only |
| `common/ratelimit.py` | `data/providers/ratelimit.py` | read by `data` (the guard, IMAP) and the domain (the worker), standard library only |

Considered and left where they are: `data/logbook.py` is a store of log
lines the domain reads like a repository, and needs nothing but
`redact`. `data/files.py` is I/O for `data` alone. `data/mail/text.py`
is the text of a mail, and the web layer reads it through `data.mail`.
`data/http/safe.py` is the network.

The rule of `common` says "stateless helpers". `redact` keeps the noted
secrets in the module, process-wide by design, and a `TokenBucket` has
state per instance. Proposed wording, for CLAUDE.md and
[ARCHITECTURE.md](ARCHITECTURE.md): `common` holds what more than one
layer needs, on the standard library, with no I/O and no state beyond
what a caller holds. `redact` is the one module with state of its own,
and its docstring says why. No other package is needed: nothing found is
of a third kind, neither data nor a helper.

Not part of the move: `common/clock.py` could take the types `Clock`
and `Sleep`. Today `ratelimit.py` declares them on `time.monotonic`, the
domain's services take a clock of `datetime`, and `delivery.py` declares
an async `Sleep` of its own. That waits for a third user (8.6).

### 8.3 Inside `data`

- **`backup` becomes `data/backup.py`**, beside `files.py`. `secrets`
  then holds cipher, keys, passwords and vault: what makes and keeps
  secrets. `backup` imports `secrets` for the cipher and `storage` for
  the file, and nothing imports `backup` but the command line.
- **An `__init__.py` exports, it does not implement.** `Store`,
  `Repositories` and `open_repositories` go to
  `storage/repositories.py`, the registry to `providers/registry.py`,
  `default_sources` and `preset_hosts` to `discovery/sources.py`. Each
  `__init__.py` then imports, and lists `__all__`, as the domain's do.
- **`mail/__init__.py` offers its modules**, `compose`, `parse`,
  `convert`, `text` and `fields`, as `activity` offers its areas, since
  `compose.build(...)` reads better than a flat list of functions. So
  `from ...mail import compose` goes through the `__init__.py`, and
  `ParsedMessage`, `from_html` and the field helpers are reached that
  way.
- **`models/__init__.py` adds `SEARCH_TEXT_PATTERN` and
  `CHANGE_KINDS`.** The seven imports of 8.1 are fixed.
- **Docstrings**: `data/__init__.py` names every package, not three.
- **The protocols leave the providers. Decided 2026-09-28:**
  `providers/protocols/` and `http/` become one package
  `data/protocols/`, the wire, one library each, in our types:

      data/
        protocols/
          transport.py   TLS, timeouts, the failures below every library
          imap.py        IMAPClient
          smtp.py        smtplib
          http/          httpx: base, safe (the SSRF guard), api, post
          oauth.py       OAuth 2.0 over http: PKCE, refresh, the token source
        providers/       the adapters: base, rules, guard, sender, registry,
                         imap/, memory/, microsoft/

  The protocol modules import nothing of `providers` today, and the
  providers use them: `imap/provider.py`, `sender.py`,
  `microsoft/signin.py` and, through `ApiClient`, `microsoft/provider.py`.
  So the path says what the docstrings say: a protocol module wraps a
  library and translates into our types, a provider composes an adapter
  from them and keeps to `rules` and `guard`. A library is then swapped
  in one module of one package, and a POP3 or JMAP wrapper has its place
  before it is needed. `sender.py` stays with the providers, since it
  uses `Guard` and `rules`. `oauth` is a flow over HTTP rather than a
  wire protocol, but it knows no provider, only the endpoints
  `microsoft/signin.py` hands it, and stays where it is. `discovery`
  reads `protocols` for HTTP, the domain only the type `HostCheck`, and
  `main.py` wires `SafeFetcher` and `WebhookPoster` as today. The three
  homes in `LIBRARY_HOMES` of the architecture test follow.

The direction after the moves, each package importing only lines
below:

```
 backup
 secrets
 storage · providers · discovery
 protocols
 mail · files
 models · logbook
```

`providers` no longer imports `secrets`, and `secrets` no longer holds
what the providers need.

### 8.4 The rules, as for the domain

The rules of sections 2 and 5 apply to `data` as they do to the domain:
a package is imported through its `__init__.py`, from the names in its
`__all__`, no cycle between packages, and the lines of 8.3. Like
`activity`, `mail` exports modules. Tests may import a module inside a
package, since they test it. `test_architecture.py` gets the three
checks for `data` by running the domain's checks over both layers.

The tests follow their modules: `test_ratelimit.py` to `tests/common/`,
and `integration/test_redact.py` too, if it tests the module alone.
`tests/data/mail/` and `tests/data/secrets/` are empty today, while
`test_html_mail.py`, `test_secrets.py`, `test_passwords.py` and
`test_backup.py` sit in `integration/`: each is checked for whether it
tests one layer, and moves if so.

### 8.5 Order of work

1. This section and ARCHITECTURE.md, one pull request of documentation.
2. `redact` and `ratelimit` to `common`, with their tests. The imports
   fixed, `data.providers` stops exporting `backoff`, the docstrings of
   `common/__init__.py` and CLAUDE.md say the new rule.
3. `backup` to `data/backup.py`.
4. `data/protocols/`: the four protocol modules and `http/` moved,
   the imports in `providers`, `discovery`, the domain and `main.py`
   fixed, `LIBRARY_HOMES` updated, the tests to `tests/data/protocols/`.
5. The three `__init__.py` to modules, the exports of `mail` and
   `models`, the seven imports fixed.
6. The architecture checks for `data`, CLAUDE.md's layout and
   CONCEPT.md 1.1 with the lines of 8.3.

Steps 2 to 6 are one branch, one commit per step, each passing all
checks. The live checks run once at the end. A backup and its restore
are covered by `test_backup.py` and `test_cli.py`, not by a live check,
so step 3 is checked by hand once: `backup` to a file, `restore` into a
fresh folder.

### 8.6 Questions answered

**Decided 2026-09-28:**

- The pacing helper keeps its name: `common/ratelimit.py`.
- `logbook` stays in `data`.
- The `Clock` and `Sleep` types stay where they are. They are merged
  into `common/clock.py` when a third user of them appears, not as part
  of this refactoring.
- CLAUDE.md points to [ARCHITECTURE.md](ARCHITECTURE.md) for the
  architecture, and ARCHITECTURE.md takes over the whole content of
  CLAUDE.md's sections "Layers of the service" and "Encapsulation and
  replaceable parts", together with what section 8 adds. That is the
  last step, in a branch of its own, after the refactoring, not part of
  it.
