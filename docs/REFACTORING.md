# Refactoring the domain layer

Proposal of 2026-09-28. The domain has grown to 27 modules side by side
in one folder. This file proposes packages for it, and a shape for the
change feed like the one [LOGGING.md](LOGGING.md) section 7 gives the
activities. Nothing changes in behaviour: modules move, names get
clearer, the API and the OpenAPI document stay as they are. What the
user decides is marked as decided, everything else is the proposal.

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
| `activity/` | new | the activities of LOGGING.md section 7 |
| `service/` | `status.py`, `recovery.py`, `servicelog.py` | the service at a glance: status, recovery key, log page |
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
  service/      status.py, recovery.py, servicelog.py
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

What each package imports, from the modules' imports today:

| Package | Imports |
|---|---|
| `rights` | nothing |
| `changes` | nothing |
| `activity` | `rights` |
| `auth` | `rights` |
| `discovery` | `rights` |
| `accounts` | `rights`, `changes`, and `sync` today (below) |
| `users` | `rights`, `auth`, `accounts` |
| `sync` | `accounts` (the adapters), `changes` |
| `mailbox` | `rights`, `accounts`, `sync`, and `changes` after section 3 (the classes at the call sites) |
| `webhooks` | `rights`, `changes`, and `sync` today for `Sleep` (below) |
| `service` | `rights`, `auth`, `accounts`, `sync`, `webhooks` |

`activity` will be imported by every package that records. `rights`
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
  between packages through `__init__.py`, no cycle between packages.
- **The web layer and `main.py`** import through the packages'
  `__init__.py` as the packages do: `from ..domain.accounts import
  AccountService`. So a package exports what the assembly wires as
  well, `Adapters`, `SyncWorker`, `WebhookDispatcher`. `web/services.py`
  stays the one place that names the services. Routes and pages import
  `Access` and the types they use the same way, in a dozen places
  today.
- **The tests** stay where they are and may import a module inside a
  package, since they test that module. Their folder is flat as well,
  70 modules. Mirroring the packages there is a step of its own, if
  wanted.

## 6. Order of work

1. This file, one pull request of documentation.
2. The change feed of section 3: the catalogue, the classes at each call
   site, `ChangeRecord`, `ChangeKind` and `FeedKind` in the data layer.
   Small, and it shows the shape before the move.
3. The packages of section 4, one commit per package, the leaves first:
   `rights`, `changes`, `auth`, `discovery`, then `accounts` with the
   cycle removed, `users`, `sync`, `mailbox`, `webhooks`, `service`.
4. The architecture tests of section 5 and CLAUDE.md.
5. `activity/` is built in its place when LOGGING.md step 2 comes.

Steps 2 to 4 are one branch, one commit per step. Each commit passes all
checks. The live checks run once at the end, since nothing they see
changes.

## 7. Open questions

- `service/` is a package while `service.py` is the module of most
  packages. Does the package of status, recovery key and log page need
  another name?
- Should the tests mirror the packages, now or later?
- Should `data/` get the same look? It is already in folders by kind
  (`models`, `mail`, `providers`, `storage`, `secrets`, `http`), which
  is why this file leaves it alone.
