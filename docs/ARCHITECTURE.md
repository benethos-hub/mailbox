# Architecture and design rules

Started 2026-09-28, a proposal. The rules of this service in short:
where a piece of code goes, how it is imported, how it is named, and
how it is moved. [CONCEPT.md](CONCEPT.md) says what the service is,
[CLAUDE.md](../CLAUDE.md) how to work in the repository and what each
module holds, [REFACTORING.md](REFACTORING.md) how the layout came to
be. This file is the part to know by heart. What the user decides is
marked as decided, everything else is the proposal.

## 1. The shape

Three layers, and imports point down only:

```
 web/      PRESENTATION   HTTP in, HTTP out. Knows who is calling.
 domain/   BUSINESS LOGIC Decides. Knows no HTTP, no SQL, no protocol.
 data/     DATA           Reads and writes. Decides nothing.
```

Beside them, read by every layer and importing none: `config.py`,
`errors.py` and `common/`. Above them, allowed to reach anywhere because
they assemble the service: `main.py`, `__main__.py`, `logs.py`.

Inside a layer, packages by area (`domain/accounts/`) or by kind
(`data/storage/`). Packages stand in lines, and a package imports only
lines below it. The lines are drawn in CONCEPT.md 1.1 and
REFACTORING.md.

A test, `tests/test_architecture.py`, checks all of this on every run.
A rule that no test checks is a wish.

## 2. Where does it go?

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
| a mail provider | a directory in `data/providers/`, behind `MailProvider`, reached through the registry |
| a library | one wrapper module, in the layer that needs it, and nowhere else. The wrapper maps into our types and our errors |
| an error | `errors.py`, a subclass of `MailboxServiceError`. `web/api/errors.py` gives it a status |
| a setting | `config.py`, as `MAILBOX_SERVICE_<NAME>`, with its default and its line in `.env.example` |
| a helper two layers need | `common/`, if it is on the standard library, does no I/O and holds no state of its own. Else it is not a helper: it belongs to one layer |
| a helper one layer needs | that layer, beside its caller |

When none of these fits, the seam is missing. Add the seam first, then
the code. A change that has to touch several layers to swap one
technology says the seam is in the wrong place.

## 3. Packages

1. **One package per area or kind**, named for what it is about, not
   for a pattern: `accounts`, not `services`. `mailbox`, not `core`.
2. **`__init__.py` exports, it does not implement.** It imports what
   others may use and lists it in `__all__`. Code longer than a few
   lines lives in a module.
3. **A package is imported through its `__init__.py`**, from the names
   in `__all__`, never a module inside it. So a package can split or
   merge its modules without its callers noticing. Tests may reach
   inside, since they test the inside.
4. **A package that offers modules as namespaces says so** in
   `__all__`: `activity` offers its areas, `data.mail` its formats.
   The caller then writes `said.SignedIn(...)` or `compose.build(...)`.
5. **No cycle between packages.** What two packages both need goes to a
   package below both, or is handed in where the services are wired
   (`build_services`), as `AccountService` gets `on_delete`.
6. **The service of a package is `service.py`.** A module is never
   named like its package: `sync/sync.py` stutters and says nothing.
7. **A package holds what belongs together,** not what is alike. Sending
   is in `mailbox`, because it builds on the calls there, not in a
   package of everything that sends.

## 4. Imports

- Relative inside the service (`from ..data.models import Account`),
  absolute in tests.
- A name comes from where it is defined, or from its package's
  `__init__.py`. Never through a third module that happens to import
  it.
- An import stands at the top of the module. The one exception is a
  library that is slow or optional to load, imported inside the
  function that uses it, in its wrapper, with a comment that says why.
- No `import *`. No re-export without `__all__`.
- A module imports what it uses, not what its callers might want.

## 5. Libraries

1. **One library, one home.** Each third-party library is imported in
   exactly one module, or one package for a framework. The
   architecture test lists the homes.
2. **Our interface, not theirs.** Code depends on a protocol this
   project defines. A library's objects, exceptions and quirks do not
   cross its wrapper.
3. **Translate at the edge.** On the way in, into `data/models/`. On
   failure, into a `MailboxServiceError`. Nothing upstream sees a raw
   exception or response.
4. **Two exceptions:** pydantic, which is how this project writes its
   types, and anyio, which is how it writes concurrency. No `asyncio`
   beside it, and a thread only where a blocking library is wrapped.
5. **The standard library is a library too.** `sqlite3`, `smtplib` and
   `ssl` have homes as httpx does.

## 6. Types and values

- **pydantic** for what crosses a boundary: the models in
  `data/models/`, settings, the shapes of the API.
- **Frozen dataclasses** for values inside a layer: an activity, a
  change, a finding. A value is made once and not changed.
- **Protocols** for seams: a repository, a provider, a key provider, a
  clock. A fake in a test fulfils the protocol, it patches nothing.
- **Ids are opaque** to callers: a prefix and hex for records
  (`common/ids.py`), a prefix and encoded JSON for cursors
  (`common/opaque.py`). No caller takes one apart.
- **`SecretStr` for every secret** the moment it is read, so it cannot
  be printed by accident. A secret in plain text is noted with
  `redact`, so it is masked if it ever reaches a line.

## 7. Errors

- The domain raises `errors`. It knows no status code. `web/api/errors.py`
  maps each class to one, `web/pages/errors.py` to a page.
- Raise where the decision is made, catch where something can be done
  about it. A `try` that only re-raises is noise.
- An error's message is for the caller: plain, without a secret,
  without the words of a mail. The data layer's wrappers translate a
  library's message before it goes up.
- A failure the service did not cause (a provider down, a bad address)
  is a subclass with a code of its own. A failure it did cause is a
  bug, reaches the log with its traceback, and answers 500.

## 8. State and time

- A service holds its state in the instance. Module-level state is
  avoided: `redact` is the one exception, process-wide by design.
- Time and sleep are handed in (`clock`, `sleep`), so a test runs in no
  time. In the domain the defaults are `utc_now` and `anyio.sleep`.
- A lock is per key (`KeyedLocks`), never global, and held for the
  shortest stretch.
- What grows is bounded: a cache has a size, a log a length, a store a
  retention or a purge.

## 9. Logging

- The domain records activities: a class from the catalogue, handed to
  `ActivityLog.record`, a sentence as LOGGING.md shapes it. No plain
  `log.info` in the domain.
- The data layer logs at `DEBUG` at most. What it notices goes up as a
  result or an error.
- The web layer logs nothing but a refused request body.
- Never in a line: a secret, the words of a mail, a recipient, a search
  term, a body.

## 10. Tests

- A test sits in the folder of the code it tests, `tests/domain/sync/`
  for `domain/sync/`. A test of several layers at once is in
  `tests/integration/`. The fakes and `conftest.py` are at the top.
- Fakes plug in at a seam: the memory provider, `httpx.MockTransport`,
  a fake `IMAPClient` at the imapclient boundary. Nothing is patched
  deep inside a library.
- No test reaches a mail server, and none skips itself without
  credentials. What needs a server is a script in `live/`.
- A rule of this file has a check in `test_architecture.py`, or it is
  not a rule yet.

## 11. Naming

- English, plain words, what a thing is: `AccountService`, `ChangeFeed`,
  `SignInThrottle`. No `Manager`, `Helper`, `Utils`, `Base` unless it
  is one.
- A module is named for its subject (`passwords.py`), not for the
  pattern it uses (`repository.py`).
- A function is a verb (`record`, `forget_account`), a value a noun, a
  boolean a question (`is_public_address`).
- The name in the API is the name in the code where they meet. A rename
  in the code never moves the OpenAPI document.
- A docstring says what the module is for and what stays out of it, in
  the first lines.

## 12. Size

- A module holds one subject, up to a few hundred lines. Past that, the
  subject has parts, and each part is a module.
- A package holds a handful of modules. Past that, it holds areas, and
  each area is a package.
- A function decides or does, and says which in its name. One that does
  both is two functions.

## 13. Refactoring

1. **Move, do not change.** A move commit moves modules and fixes
   imports, nothing else. Behaviour, the API and the OpenAPI document
   stay the same. A change of behaviour is its own commit, before or
   after.
2. **A concept first,** in `docs/`, with the reason, the target layout,
   the direction of imports and the order of work. What the user
   decides is marked as decided. Then one branch, one commit per step,
   every commit green on all checks.
3. **Leaves first.** Move what nothing imports from, then what imports
   it, up to the top. A cycle is removed before the move that would
   expose it.
4. **Every rule gets its check** in `test_architecture.py` in the same
   branch, so the layout cannot drift back.
5. **The documents move with the code:** CLAUDE.md's layout, CONCEPT.md
   1.1, the concept's "built" note, the roadmap, in the same commit.
6. **Tests move, they do not change.** Their imports change, their
   assertions do not. A test that has to change to pass says the move
   changed behaviour.
7. **Rename only with the API untouched.** A Python name is free to
   change. A name in a route, a field, an `operationId`, an activity
   name or a change kind is a contract.
8. **Live checks once at the end** of a branch that moves code, since
   nothing they see changes.

## 14. Questions

**Decided 2026-09-28:** this file takes over the sections "Layers of
the service" and "Encapsulation and replaceable parts" of CLAUDE.md in
full, with what REFACTORING.md section 8 adds, and CLAUDE.md points
here. That happens after the refactoring of section 8, in a branch of
its own.

Open:

- Section 12's sizes are a feeling, not a measure. Should the
  architecture test count lines?
