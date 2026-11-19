# Architecture: the rules

Part of the [architecture](../ARCHITECTURE.md): sections 5 to 17.

## 5. Packages

1. **One package per area or kind**, named for what it is about, not
   for a pattern: `accounts`, not `services`. `mailbox`, not `core`.
2. **`__init__.py` exports, it does not implement.** It imports what
   others may use and lists it in `__all__`. Code longer than a few
   lines lives in a module. The exception is the `__init__.py` that
   puts its package together: `main()` and the parser in `cli/`,
   `install()` and its helpers in `web/`, `web/api/` and `web/pages/`
   (section 3).
3. **A package is imported through its `__init__.py`**, from the names
   in `__all__`, never a module inside it. So a package can split or
   merge its modules without its callers noticing. Tests may reach
   inside, since they test the inside.
4. **A package that offers modules as namespaces says so** in
   `__all__`: `activity` offers its areas, `data.mail` its formats.
   The caller then writes `said.UiSignIn(...)` or `compose.message(...)`.
5. **No cycle between packages.** What two packages both need goes to a
   package below both, or is handed in where the services are wired
   (`build_services`), as `AccountService` gets `on_delete`.
6. **The service of a package is `service.py`.** A module is never
   named like its package: `sync/sync.py` stutters and says nothing.
7. **A package holds what belongs together,** not what is alike. Sending
   is in `mailbox`, because it builds on the calls there, not in a
   package of everything that sends.

## 6. Imports

- Relative inside the service (`from ..data.models import Account`),
  absolute in tests.
- A name comes from where it is defined, or from its package's
  `__init__.py`. Never through a third module that happens to import
  it.
- An import stands at the top of the module. There are two exceptions.
  A library that is slow or optional to load is imported inside the
  function that uses it, in its wrapper, with a comment that says why.
  A command in `cli/` imports in its `run()` what only that command
  needs, so the parser and the other commands do not load it.
- No `import *`. No re-export without `__all__`.
- A module imports what it uses, not what its callers might want.

## 7. Libraries

1. **One library, one home.** Each third-party library is imported in
   exactly one module, or one package for a framework: IMAPClient only
   in `data/protocols/imap/`, `cryptography` only in
   `data/secrets/cipher.py`, FastAPI only under `web/` and in
   `assembly/web.py`, which builds the app. When it is
   needed somewhere else, its wrapper is extended, it is not imported a
   second time. The architecture test lists the homes.
2. **Our interface, not theirs.** Code depends on a protocol this
   project defines (`Reads`, a repository, a key provider), never
   on a third-party type. A library's objects, exceptions and quirks do
   not cross its wrapper.
3. **Translate at the edge.** On the way in, into `data/models/`. On
   failure, into a `MailboxServiceError`. Nothing upstream sees a raw
   exception or response.
4. **Two exceptions:** pydantic, which is how this project writes its
   types, and anyio, which is how it writes concurrency. No `asyncio`
   beside it, and a thread only where a blocking library is wrapped.
5. **The standard library is a library too.** `sqlite3`, `smtplib`,
   `poplib`, `ssl` and `email` have homes as httpx does.

## 8. Encapsulation and replaceable parts

This project is built from parts that can be exchanged one at a time. A
mail library, the database, the web framework or a whole provider should be
replaceable by rewriting **one module**, without the rest of the code
noticing. Every change is measured against that.

**The rules that make it work**, with those of section 7:

1. **Dependencies point inward.** Routes know the domain services and
   the models. The models know nothing of FastAPI, SQLite or IMAP. The
   domain never imports the layer above it.
2. **Wire it in one place.** Which implementation is used is decided where
   the app is assembled (`create_app`, `build_services`, settings), never
   inside the code that uses it. That is also how tests swap in fakes.
3. **The contract is the boundary.** Between the service and the
   client or the MCP server there is only the REST API. Neither the
   client nor the MCP package depends on or imports the service package.
   The MCP package's `tests/test_boundary.py` and the client's
   `tests/test_architecture.py` check it. `mailbox-common` lies below
   the service and the MCP server and sees neither, so it is no way
   from one to the other.

**The seams, and what sits behind each:**

| Seam | Defined in | Implementations | Exchangeable for |
|---|---|---|---|
| Mail provider | `data/providers/base.py` (`Reads`, which every adapter implements, and `Writes`, `Deletes`, `Drafts`, `Sends`, `Watches`, `Deltas`, `FlagChanges`, `Threads`, `Summaries`, `Places`, `ServerNames` for what it may do beyond, `PROTOCOLS` for the protocol behind each capability. `Capability` and `Abilities` of `data/models/accounts.py`, answered by each adapter's `abilities()` from its server), registry in `data/providers/registry.py`. The domain checks what each operation needs and answers 501 for a lack (`domain/accounts/abilities.py`, `NEEDS`) | memory, imap, microsoft, pop3, jmap, gmail | another protocol or library, e.g. `aioimaplib` for IMAPClient |
| Sending | `data/protocols/smtp.py` (`SmtpSession`), and `data/providers/sender.py` (`SmtpSender`), which adapters without sending of their own (IMAP, POP3) hold | stdlib smtplib | e.g. aiosmtplib |
| Web layer | `web/` | FastAPI, Jinja2 for the UI | another framework, as long as the OpenAPI document stays the same |
| Account and user store | `data/storage/` (`AccountRepository`, `UserRepository`, `RoleRepository`, `TokenRepository`, `PasswordRepository`, `KeyRepository`, `CredentialRepository`, `MessageIndexRepository`, `IdempotencyRepository`, `SendLogRepository`, `ChangeLogRepository`, `WebhookRepository`, `AuditRepository`, `LinkRepository`, `TotpRepository`, `RecoveryCodeRepository`, `PasskeyRepository`) | in-memory, SQLite | another database |
| Autodiscovery source | `data/discovery/` (`DiscoverySource`) | presets, ISP autoconfig, JMAP well-known and SRV, ISPDB, MX (planned: Microsoft realm, SRV for IMAP and SMTP, guessing) | any further lookup, or one switched off |
| HTTP | `data/protocols/http/` (`SafeFetcher`, `ApiClient`, `ServerClient`) | httpx | another HTTP client |
| OAuth token source | `TokenSource` in `data/providers/base.py`, made in `data/protocols/oauth/tokens.py`, each OAuth provider's endpoints and scopes in its own directory, reached through `sign_in` in the registry | refresh token in the vault, access token in memory | another token store |
| Secret encryption | `KeyProvider` in `data/secrets/keys.py` | keyring, file, env | a secret manager such as Vault |
| Folders for settings and data | `folders()` in `config.py`, `system_folders` in `paths/folders.py` of `mailbox-common` | named file, the repository's layout, the system's folders through platformdirs | another lookup, e.g. a system-wide folder |
| Settings | `FileSettings` and `load` in `settings/files.py` of `mailbox-common`, the base of the service's and the MCP server's `Settings` | pydantic-settings | another reader of the environment and a settings file |
| Password hashing | `PasswordHasher` in `data/secrets/passwords.py` | scrypt from the standard library | Argon2 |
| Authentication | credential kinds of a user (CONCEPT 7.5, [AUTHENTICATION.md](../AUTHENTICATION.md)) | API token, password for the UI | OAuth client credentials |
| Second factor | `SecondFactors` in `domain/auth/factors.py`, the frame over its methods and the recovery codes | TOTP (`domain/auth/totp.py`, `data/secrets/totp.py`), passkeys (`domain/auth/passkeys.py`, `data/secrets/passkeys.py`) | a further method beside them |
| Passkeys | `registration`, `registered`, `authentication` and `asserted` in `data/secrets/passkeys.py` | fido2 | another WebAuthn library |
| QR code | `data_uri` in `web/pages/qr.py` | segno | another QR library |
| Client ↔ service | the REST API, `docs/openapi.json` | the package `mailbox-client`: each endpoint in `endpoints/`, sent by an async and a sync client over httpx. The MCP server uses it | a generated client, another HTTP library in `client.py`, `sync.py`, `calls.py`, `environment.py` and the modules that read an answer |

**When you add something new**, ask first where its seam is. A new
provider is a new module behind `Reads`, not a branch in a route. A
new library gets a wrapper before it gets a caller. If a change needs edits
in several layers to swap one technology, the seam is in the wrong place:
fix that first, and say so.

**Tests use the seams too.** Fakes are plugged in at an interface (the
memory provider, `httpx.MockTransport`, a fake `IMAPClient` at the
imapclient boundary), never by patching deep inside a library.

## 9. Types and values

- **pydantic** for what crosses a boundary: the models in
  `data/models/`, settings, the shapes of the API.
- **JSON from a server is read into a shape at the edge**, once:
  a `Shape` of `data/protocols/wire.py`, in the protocol module or the
  adapter's `shapes.py`. The code behind it reads typed fields, no
  `dict.get` and no `isinstance`. A body of another shape is the
  server's failure, a `ProviderError` whose text names none of the
  input.
- **Frozen dataclasses** for values inside a layer: an activity, a
  change, a finding of discovery. A value is made once and not changed.
  What an id, a cursor or an account's settings carry is read back
  into one with named fields, not a tuple or a dict.
- **Protocols** for seams: a repository, a provider, a key provider, a
  clock. A fake in a test fulfils the protocol, it patches nothing.
- **Ids are opaque** to callers: a prefix and hex for records
  (`values/secret.py` of `mailbox-common`), a prefix and encoded JSON
  for cursors (`common/opaque.py`). No caller takes one apart.
- **`SecretStr` for every secret** the moment it is read, so it cannot
  be printed by accident. A secret in plain text is noted with
  `redact`, so it is masked if it ever reaches a line.
- **At a package boundary, values travel as named records, never as
  tuples or dicts.** What one package returns to another is a frozen
  dataclass (`frozen=True, slots=True`) with a name for every field.
  What it takes in are plain values (`str`, `Path`, `int`), never a type
  of the caller. Inside a package, between two private functions, a
  tuple is fine.
  Why: the caller reads `found.config`, not `found[0]`. A record can
  gain a field without breaking a caller. mypy checks names and types,
  where `tuple[Path, Path]` says nothing. Plain values at the entrance
  keep `mailbox-common` free of the types of the packages above it.
  Cost: one class per answer, one object per call, with slots a fraction
  of a microsecond. The one exception is a hot loop, such as one record
  per line while parsing thousands of messages. Decide there on purpose
  and say why in the docstring.
  Example: `benethos_mailbox_common.paths.folders`: `system_folders(app)`
  returns `SystemFolders(config, data)`, not a tuple.
  The answers of the MCP server's tools are named too, as `TypedDict`s
  in `answers.py`: the MCP library makes each tool's output schema from
  them, and a key without a value stays out of the answer rather than
  going as null.
  `tests/test_boundaries.py` at the root of the repository checks it for
  the four packages: what each offers, and the methods of the domain services
  the web layer reaches. Its `ALLOWED` names what stays, with the
  reason, such as a lookup by key or the free JSON of an account's
  settings.

## 10. Errors

- The domain raises `errors`. It knows no status code. `web/errors.py`
  maps each class to one. `web/api/errors.py` answers it in the error
  envelope, `web/pages/errors.py` as a page.
- Raise where the decision is made, catch where something can be done
  about it. A `try` that only re-raises is noise.
- An error's message is for the caller: plain, without a secret,
  without the words of a mail. The data layer's wrappers translate a
  library's message before it goes up.
- A failure the service did not cause (a provider down, a bad address)
  is a subclass with a code of its own. A failure it did cause is a
  bug, reaches the log with its traceback, and answers 500.

## 11. State and time

- A service holds its state in the instance. Module-level state is
  avoided: `redact` is the one exception, process-wide by design.
- What the web layer keeps on `app.state` is read with its type in
  `web/state.py`, and nowhere else. What a page request keeps on
  `request.state` is put and read by `current` and `found_for` in
  `web/pages/session.py`.
- Time and sleep are handed in (`clock`, `sleep`), so a test runs in no
  time. In the domain the defaults are `utc_now` and `anyio.sleep`.
- A lock is per key (`KeyedLocks`), never global, and held for the
  shortest stretch.
- What grows is bounded: a cache has a size, a log a length, a store a
  retention or a purge.

## 12. Logging

- The domain records activities: a class from the catalogue, handed to
  `ActivityLog.record`, a sentence as LOGGING.md shapes it. No plain
  `log.info` in the domain.
- The data layer logs at `DEBUG` at most. What it notices goes up as a
  result or an error.
- The web layer records two activities of its own, a refused request
  body and a caller out of requests, since the domain never sees those
  requests. It logs nothing else.
- Never in a line: a secret, the words of a mail, a recipient, a search
  term, a body.

## 13. Tests

- A test sits in the folder of the code it tests, `tests/domain/sync/`
  for `domain/sync/`. A test of several layers at once is in
  `tests/integration/`. The fakes and `conftest.py` are at the top.
  A fixture that tests of more than one module take is in the
  `conftest.py` of their nearest common folder, never imported from a
  test module. A test module defines no fixture under the name of one
  in a `conftest.py` above it, and two test modules of a folder share
  no fixture name. A helper they share is in a module of its own there,
  named after its subject: a fake in `<subject>_fake.py`, a part of a
  large one in `<subject>_fake_<part>.py`, an adapter on its fake in
  `<kind>_adapter.py`, anything else in
  `<subject>_helpers.py`. The clocks a test moves itself are in
  `clocks.py`. No test module imports another, every other module
  is named so and lies in the nearest common folder of the modules that
  import it, which `tests/test_code_rules.py` at the root checks in all
  four packages.
- The UI in real browsers is a suite apart,
  `packages/mailbox-service/tests/browser/`, not beside the code of
  `web/pages/` it tests: it needs the dependency group `browser`,
  Playwright's browsers and fixtures of its own in its `conftest.py`,
  and it is collected only with `MAILBOX_BROWSER_TESTS=1`
  (CLAUDE.md, Verifying).
- What checks the repository across the four packages, the publishing,
  the workflows, the READMEs, the trees of section 3, the project
  layout of CLAUDE.md, the boundaries, the rules for the tests of every
  package and for `live/`, and the JavaScript the UI ships, is in
  `tests/` at its root. Beside them
  `installed_check.py` is not a test: the packages as installed, as real
  processes, run by hand and by `freshness.yml`. Nor is `interface.py`,
  which writes the public interface of `mailbox-client` and
  `mailbox-common` for the records in `docs/` that `test_interfaces.py`
  holds to the code. Each package's tests stay its own and run alone.
- The client is held to the API by its own tests: every operation is a
  method of both clients (`test_operations.py`), every record holds the
  fields of its schema (`models/test_fields.py`), and every request it
  builds is one the API takes, its method, path, parameters and body
  (`test_requests.py`).
- Fakes plug in at a seam: the memory provider, `httpx.MockTransport`,
  a fake `IMAPClient` at the imapclient boundary. Nothing is patched
  deep inside a library.
- No test reaches a mail server, and none skips itself without
  credentials. What needs a server is a script in `live/`. What the
  scripts share is in `live/checks/`, one module per subject. What a
  script does with mail on the way goes through the Python client. What
  it asks of the API itself, a status code or an error code, it asks
  with httpx, or with FastAPI's test client for a service it started in
  its own process.
- A rule on the layout has a check in `test_architecture.py`, in the
  service also `test_packages.py` and `test_assembly.py`, or, for the
  code itself, `test_code_rules.py`, of a package for its own source and
  at the root for what spans the packages, or it is not a rule yet: the
  layers, the lines, the imports through `__init__.py`, the homes of the
  libraries, who logs what, the sizes of section 15. Naming and style
  (section 14) are for the review.

## 14. Naming

- English, plain words, what a thing is: `AccountService`, `ChangeFeed`,
  `SignInThrottle`. No `Manager`, `Helper`, `Utils`, `Base` unless it
  is one.
- A module is named for its subject (`passwords.py`), not for the
  pattern it uses (`repository.py`).
- A function is a verb (`record`, `forget_account`), a value a noun, a
  boolean a question (`is_public_address`). An exception ends in
  `Error`. Ruff checks the names (pep8-naming).
- A mapper of an adapter (`mappers.py`) is named for what it makes, the
  same in every adapter: `folder`, `folders`, `summary`, `message`,
  `keywords`. Called as `mappers.message(...)`, it reads as
  what it answers. The way back to the provider is named for the
  provider's shape: `imap_flag`, `keyword_patch`, `query_filter`.
- The name in the API is the name in the code where they meet. A rename
  in the code never moves the OpenAPI document.
- A docstring says what the module is for and what stays out of it, in
  the first lines.

## 15. Size

- A module holds one subject, at most 500 lines, a class at most 30
  methods. The same holds for the tests and the live checks in `live/`.
  `test_architecture.py` of the client and the MCP server checks both
  for its package and its tests, that of `mailbox-common` the length
  of its modules, `test_code_rules.py` of the service for the
  service and its tests, `tests/test_code_rules.py` at the root for the
  tests there and `live/`. Past that, the subject has
  parts, and each part is a module.
- A package holds a handful of modules. Past that, it holds areas, and
  each area is a package.
- A function decides or does, and says which in its name. One that does
  both is two functions. Ruff checks its size: a complexity of at most
  10, at most 12 branches and 50 statements. One beyond is split, never
  excused with `noqa`.

## 16. Refactoring

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
5. **The documents move with the code:** section 3 of this file,
   CONCEPT.md 1.1, the concept's "built" note, the roadmap, in the same commit.
6. **Tests move, they do not change.** Their imports change, their
   assertions do not. A test that has to change to pass says the move
   changed behaviour.
7. **Rename only with the API untouched.** A Python name is free to
   change. A name in a route, a field, an `operationId`, an activity
   name or a change kind is a contract.
8. **Live checks once at the end** of a branch that moves code, since
   nothing they see changes.

## 17. Questions answered

**Decided 2026-09-28:** the architecture test counts no lines. Section
15 is a rule for the review. Superseded by REFACTORING.md 12.3: the
tests count lines, as section 15 says.
