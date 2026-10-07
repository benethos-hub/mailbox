# Architecture and design rules

Decided 2026-09-28 as a whole. The rules of this service: the layers,
the modules and the seams, where a piece of code goes, how it is
imported, how it is named, and how it is moved.
[CONCEPT.md](CONCEPT.md) says what the service is,
[CLAUDE.md](../CLAUDE.md) how to work in the repository,
[REFACTORING.md](REFACTORING.md) how the layout came to be. This file is
the reference: a change that adds a module, a package, a library or a
seam is measured against it.

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

Inside a layer, packages by area (`domain/accounts/`) or by kind
(`data/storage/`). Packages stand in lines, and a package imports only
lines below it. The lines are drawn in section 2.

A test, `tests/test_architecture.py`, checks all of this on every run.
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
- **`common/` is not a drawer.** Only what more than one layer needs, on
  the standard library, with no I/O and no state beyond what a caller
  holds. `redact` is the one module with state of its own, and its
  docstring says why. What one layer needs stays in that layer.
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
   locks · paging · bounded
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
  `ActivityLog.record`, a sentence as docs/LOGGING.md section 3 shapes
  it. The data layer logs at `DEBUG` at most: what it notices goes up as
  a result or an error.

`tests/test_architecture.py` checks the direction, the cross-cutting
modules, that `common/` stays on the standard library, that FastAPI stays in
`web/` (and `assembly/`), that providers are reached through the registry,
that the domain picks no storage implementation, and that SQLite is
reached through `data/storage/` alone. It also checks that the data
layer logs nothing above `DEBUG` and the domain nothing but activities,
and that the packages of the domain and of data are imported through
their `__init__.py`, export what others import, have no cycle, and keep
their lines. Nothing below reaches `assembly/` or `cli/`, the assembly
knows no command, and the modules of both keep their lines: in
`assembly/` `web`, `lifecycle`, `domain`, then `storage`, `secrets` and
`providers`, then `services`. In `cli/` each command reaches `common`,
never another command. The client and the MCP server have an
architecture test of their own (section 3).
An import or a line that breaks a rule fails the suite.

## 3. The code, module by module

What each package and module of the service holds. A new module gets
its line here in the same commit.

```
packages/mailbox-service/
  src/benethos_mailbox_service/
    __main__.py         # python -m, calls cli/
    cli/                # the command line, one module per command
      __init__.py       # main(), the parser built from the commands
      common.py         # --env-file, the errors a command reports, the
                        #   master key from the key provider or a
                        #   recovery key
      serve.py          # the REST API and the UI, the log first
      openapi.py        # the OpenAPI document on stdout
      paths.py          # where the settings and the data are
      users.py          # create-admin, set-password
      keys.py           # init, import, generate
      backup.py         # write a backup, verify one
      restore.py        # replace the database with a backup
    assembly/           # builds the service, picks implementations,
                        #   decides nothing else
      storage.py        # the repositories, the audit, the activity log
      secrets.py        # the key provider, the vault
      providers.py      # the guard of every connection, the adapters'
                        #   factory, OAuth apps, kinds offered, discovery
      domain.py         # build_services: the domain services wired
      services.py       # Services, as web/ and cli/ reach them
      lifecycle.py      # opened() for a command, serving() for the app
      web.py            # create_app, openapi_json
    logs.py             # assembly: the log of serve, format, level, masking
    config.py           # cross-cutting: Settings (MAILBOX_SERVICE_* env and
                        #   the .env), the folders that apply: named,
                        #   the repository's, the system's (platformdirs)
    errors.py           # cross-cutting: MailboxServiceError hierarchy, no HTTP
    common/             # cross-cutting: helpers several layers share,
                        #   standard library only
      ids.py            # ids of own records: acc_, usr_, msg_, ... + 64 hex
      opaque.py         # opaque ids and cursors: prefix + base64 JSON,
                        #   and base64 without padding, for passwords and
                        #   OAuth too
      clock.py          # utc_now, the default clock of the services,
                        #   log_time: the time of every log line,
                        #   iso and parse_iso: a time as text, in UTC
      redact.py         # secrets noted once, masked in every text
      ratelimit.py      # pacing: a token bucket and a backoff
      plaintext.py      # the text of an HTML body, for a mail and a page
      hosts.py          # host names in one form: ASCII, Unicode, syntax
      sizes.py          # MIB, and a size in megabytes for a message
      chunks.py         # batched: a sequence in slices
    web/                # PRESENTATION: HTTP only, FastAPI lives here
      __init__.py       # install: both front ends, errors to the right one
      services.py       # the domain services as dependencies, for both
      urls.py           # this service's public address, OAuth callback
      limits.py         # the size of a request body, the requests a
                        #   minute, for both
      errors.py         # error class -> status code, for both
      responses.py      # download: bytes to save as a file, for both
      search.py         # the search of a message list by its query names
      api/              # the JSON API: /health open, the rest under /v1
        deps.py         # bearer authentication, services per request
        schemas/        # shapes that exist only at the HTTP boundary,
                        #   one module per subject: accounts, oauth,
                        #   mail, users, tokens, status, errors
        errors.py       # the error envelope, the errors routes document
        routes/         # one router per resource
      pages/            # the configuration UI under /ui, not in OpenAPI
        deps.py         # who is signed in, the CSRF check, if_allowed
        navigation.py   # the sidebar entries a caller may open, breadcrumbs
        filters.py      # the filter bar of a list: its fields and chips
        session.py      # sign-in with a password, server-side sessions
        templates.py    # Jinja2: filters, render, Post/Redirect/Get
        grants.py       # the grant editor's rows, read back into grants
        mailform.py     # the mail form: fields to a message, shown again
        forms.py        # form errors, failing: back with the message,
                        #   model_of and text_of: what a form holds
        rights.py       # what the mail pages offer, by the rights on an account
        effective.py    # a user's effective rights, grouped for reading
        errors.py       # errors as a page
        routes/         # one module per area
        templates/      # base, partials, components (macros), pages
        static/         # app.css, app.js, vendored htmx
    domain/             # BUSINESS LOGIC: decides, knows no HTTP
                        # one package per area (docs/REFACTORING.md),
                        #   the service of a package in service.py
      rights/           # who may do what: permissions (the catalogue of
                        #   rights and groups), Access (one caller)
      auth/             # proving who calls: AuthService, Passwords,
                        #   SignInThrottle
      users/            # UserService: users, roles, tokens
      accounts/         # AccountService, Adapters (the live adapter per
                        #   account), OAuthService, abilities: 501 for
                        #   what an adapter does not implement
      discovery/        # DiscoveryService: trust, ranking, cache, limits
      mailbox/          # MailboxService, the facade for mail: calls under
                        #   our ids, lists across accounts, replies,
                        #   sending and drafts (outgoing), grant limits
                        #   and the send audit, Idempotency-Key
      sync/             # SyncService (stable message ids, the sync pass),
                        #   SyncWorker (polling and IDLE)
      changes/          # what changed in a mailbox, for clients:
                        #   MailboxChange, one class per kind, ChangeFeed
      webhooks/         # WebhookService, WebhookDispatcher (signed posts,
                        #   retries)
      system/           # the service at a glance: StatusService, and to
                        #   admin RecoveryKey and ServiceLog
      activity/         # what was done, and by whom: the service log.
                        #   Activity, ActivityLog, catalogue/ one module
                        #   per area: activity.<area>.<name>
                        #   (docs/LOGGING.md 7.2), Audit: those marked
                        #   audited kept and read (docs/AUDIT.md)
      locks.py          # KeyedLocks: one lock per key, for the services
      paging.py         # the cursors this service hands out itself, the
                        #   page they continue
      bounded.py        # trim: tables in memory with a cap
      rounds.py         # rounds: the background loops of the services
    data/               # DATA: reads and writes, decides nothing. A
                        #   package is imported through its __init__.py
      models/           # provider-neutral types, one module per subject:
                        #   accounts, users, folders, messages, batch,
                        #   sending, paging, discovery, audit,
                        #   changes, webhooks
      mail/             # messages in RFC 5322, whatever protocol carries
                        #   them. __init__.py offers the modules
        compose.py      # outgoing messages as bytes (email)
        parse.py        # incoming bytes parsed (imap-tools' mail parser)
        convert.py      # a parsed message to Message / MessageSummary
        fields.py       # one header field: a Message-ID as one token,
                        #   an address in Unicode
      protocols/        # the wire, one library each, in our types:
                        #   imap.py (IMAPClient), smtp.py (smtplib),
                        #   pop3.py (poplib), jmap/ (JMAP over http:
                        #   client.py, shapes.py, answers.py),
                        #   oauth.py (OAuth 2.0 with PKCE, sign-in
                        #   with a code, refresh, token source),
                        #   transport.py: the Server, TLS,
                        #   timeouts, the failures below every library,
                        #   wire.py: JSON a server sends read into
                        #   shapes (pydantic)
        http/           # httpx: base.py (the client, the capped read),
                        #   safe.py (hosts users typed, SSRF guard),
                        #   api.py (JSON to a provider's known hosts),
                        #   server.py (JSON to a server an account
                        #   names, at the checked address),
                        #   post.py (posts to webhook receivers)
      providers/        # the adapters: base.py, rules.py, registry.py
                        #   (build_provider, sign_in, probe_server)
        guard.py        # pacing, retries, blocked logins, for any adapter
        sender.py       # SmtpSender: sending for IMAP, POP3, ...
        mailserver.py   # MailServerAdapter: what IMAP and POP3 share,
                        #   the server, the login, the guard, SMTP
        imap/, memory/, # one directory per provider (adapter),
        microsoft/,     #   provider.py the adapter, mappers.py the
        pop3/, jmap/    #   translation, shapes.py what the provider
                        #   sends as JSON, the rest one module per
                        #   subject.
                        #   imap: connect.py, mailbox.py (one session
                        #   and its folders), folders, messages, drafts,
                        #   sync, watch (IDLE).
                        #   jmap: over data/protocols/jmap/,
                        #   account.py (one account's calls), folders,
                        #   messages, drafts, sending, changes.
                        #   microsoft: graph.py (Graph over
                        #   data/protocols/http), signin.py its
                        #   endpoints and the scopes it needs.
                        #   pop3: one inbox, a session per step
      storage/          # own records, one module per subject, table.py
                        #   for the in-memory ones, sqlite/ the database,
                        #   sqlite/migrations/ the base, the registry,
                        #   versions/ one class per schema version,
                        #   repositories.py opens one of them
      secrets/          # envelope encryption, key providers, password
                        #   hashes, the vault of the credentials
      backup.py         # encrypted backups of the database, restore
      files.py          # files for the owner alone (0600): database, backup, key
      logbook.py        # the newest log lines in memory, for the log page
      discovery/        # autodiscovery sources and their helpers,
                        #   sources.py puts them in order
```

The Python client of the REST API is a package of its own. It cannot
import the service or the MCP server, and its
`tests/test_architecture.py` checks that, with the lines below and httpx
in the modules that make or read a request.

```
packages/mailbox-client/
  src/benethos_mailbox_client/
    __init__.py         # what a caller imports: both clients, the
                        #   records, the errors, message_body()
    client.py           # MailboxClient: sends the calls with
                        #   httpx.AsyncClient, one line per method
    sync.py             # SyncMailboxClient: the same calls with
                        #   httpx.Client
    endpoints.py        # each endpoint once: method, path, query,
                        #   body, how its answer becomes a record.
                        #   Sends nothing
    wire.py             # what both share: address and token, Call,
                        #   reading an answer, an error or a failure
    models.py           # the records the clients answer with
    errors.py           # MailboxError and its subclasses
```

**An endpoint of the client** is a function in `endpoints.py` that
answers a `Call`, and a one-line method on each client that sends it.
Its test is in `tests/test_endpoints.py` and runs for both clients.
Neither client knows a path or a field: when the two differ in more
than `await`, the difference belongs in `wire.py` or `endpoints.py`.

The MCP server is a package of its own, built on the client. It
cannot import the service, and `tests/test_boundary.py` checks that.

```
packages/mailbox-mcp/
  src/benethos_mailbox_mcp/
    __main__.py         # python -m, calls cli.py
    cli.py              # the command line: options, MAILBOX_MCP_*, the
                        #   log, the start over stdio or HTTP
    server.py           # MCPServer: the tools the token's rights allow,
                        #   each logged when it fails
    transport.py        # streamable HTTP: bearer guard, host check (uvicorn)
    tools/              # one module per kind, each with its part of TOOLS
      base.py           # Tool, reads()/changes(), the shared client,
                        #   result(): text and images
      compose.py        # what drafts and sending share: addresses, the
                        #   message a tool's arguments describe
      accounts.py       # list_accounts, which reports the kinds
      reading.py        # folders, search, a message, what is new,
                        #   attachments
      writing.py        # change messages, create a folder
      drafts.py         # list, write, replace, delete drafts
      sending.py        # send a mail, send a draft
    render.py           # what the model sees of mail, marked as foreign
    pdf.py              # PDF pages as PNG (pypdfium2)
    client.py           # the client package's MailboxClient, the
                        #   one way to the REST API
    models.py           # the client package's records
    errors.py           # ToolError, and the client's errors turned
                        #   into one for the model
    config.py           # the optional .env, put into the environment
                        #   (platformdirs, python-dotenv)
```

`tests/test_architecture.py` of the MCP package keeps the modules in
the lines of REFACTORING.md 10.2, the tools behind their package, and
one home per library.

**A tool of the MCP server** is a function in `tools/<kind>.py` with
its line in that module's `TOOLS`: its title, the rights it needs, and
whether it is read-only, destructive or idempotent. The server
registers it only for a token that holds one of those rights. The
function is thin: it names what it wants in its own terms, the client
package makes the request, and `render.py` shapes what the model sees, with
mail content inside the foreign-content marker. A tool never spells
out a path, a query name or a field of the API, and never speaks HTTP
itself. Its docstring is the description the model reads. An argument
may carry a description of its own and its bounds, in `Annotated` with
`Field`. The server checks the bounds before the tool runs. Its test is
in `tests/tools/`, against `httpx.MockTransport`, and the README's table
names it.

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
| a tool of the MCP server | `tools/<kind>.py` of the MCP package with its line in `TOOLS` there, its request in the client package, its answer through `render.py` (section 3) |
| a request of the Python client | `endpoints.py` of the client package, and one line on each client (section 3) |
| a library | one wrapper module, in the layer that needs it, and nowhere else. The wrapper maps into our types and our errors |
| an error | `errors.py`, a subclass of `MailboxServiceError`. `web/errors.py` gives it a status |
| a setting | `config.py`, as `MAILBOX_SERVICE_<NAME>`, with its default and its line in `.env.example` |
| a helper two layers need | `common/`, if it is on the standard library, does no I/O and holds no state beyond what a caller holds. Else it is not a helper: it belongs to one layer |
| a helper one layer needs | that layer, beside its caller |

When none of these fits, the seam is missing. Add the seam first, then
the code. A change that has to touch several layers to swap one
technology says the seam is in the wrong place.

## 5. Packages

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

## 6. Imports

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

## 7. Libraries

1. **One library, one home.** Each third-party library is imported in
   exactly one module, or one package for a framework: IMAPClient only
   in `data/protocols/imap.py`, `cryptography` only in
   `data/secrets/cipher.py`, FastAPI only under `web/`. When it is
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
5. **The standard library is a library too.** `sqlite3`, `smtplib` and
   `ssl` have homes as httpx does.

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
3. **The contract is the boundary.** Between the service and the other
   two packages there is only the REST API. Neither the client nor the
   MCP package depends on or imports the service package. The MCP
   package's `tests/test_boundary.py` and the client's
   `tests/test_architecture.py` check it.

**The seams, and what sits behind each:**

| Seam | Defined in | Implementations | Exchangeable for |
|---|---|---|---|
| Mail provider | `data/providers/base.py` (`Reads`, which every adapter implements, and `Writes`, `Deletes`, `Drafts`, `Sends`, `Watches`, `Deltas` for what it can beyond; `Capability`, `capabilities_of`), registry in `data/providers/registry.py`. The domain answers 501 for a missing protocol (`domain/accounts/abilities.py`) | memory, imap, microsoft, pop3, jmap (planned: gmail) | another protocol or library, e.g. `aioimaplib` for IMAPClient |
| Sending | `data/protocols/smtp.py` (`SmtpSession`), and `data/providers/sender.py` (`SmtpSender`), which adapters without sending of their own (IMAP, POP3) hold | stdlib smtplib | e.g. aiosmtplib |
| Web layer | `web/` | FastAPI, Jinja2 for the UI | another framework, as long as the OpenAPI document stays the same |
| Account and user store | `data/storage/` (`AccountRepository`, `UserRepository`, `RoleRepository`, `TokenRepository`, `PasswordRepository`, `KeyRepository`, `CredentialRepository`, `MessageIndexRepository`, `IdempotencyRepository`, `SendLogRepository`, `ChangeLogRepository`, `WebhookRepository`) | in-memory, SQLite | another database |
| Autodiscovery source | `data/discovery/` (`DiscoverySource`) | presets, ISP autoconfig, JMAP well-known, ISPDB, MX (planned: Microsoft realm, SRV for IMAP and SMTP, guessing) | any further lookup, or one switched off |
| HTTP | `data/protocols/http/` (`SafeFetcher`, `ApiClient`, `ServerClient`) | httpx | another HTTP client |
| OAuth token source | `TokenSource` in `data/providers/base.py`, made in `data/protocols/oauth.py`, each OAuth provider's endpoints and scopes in its own directory, reached through `sign_in` in the registry | refresh token in the vault, access token in memory | another token store |
| Secret encryption | `KeyProvider` in `data/secrets/keys.py` | keyring, file, env | a secret manager such as Vault |
| Folders for settings and data | `folders()` in `config.py` | named file, the repository's layout, the system's folders through platformdirs | another lookup, e.g. a system-wide folder |
| Password hashing | `PasswordHasher` in `data/secrets/passwords.py` | scrypt from the standard library | Argon2 |
| Authentication | credential kinds of a user (CONCEPT 7.5) | API token, password for the UI | TOTP, OAuth client credentials |
| Client ↔ service | the REST API, `docs/openapi.json` | the package `mailbox-client`: each endpoint in `endpoints.py`, sent by an async and a sync client over httpx. The MCP server uses it | a generated client, another HTTP library in `client.py` and `sync.py` |

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
- **Protocols** for seams: a repository, a provider, a key provider, a
  clock. A fake in a test fulfils the protocol, it patches nothing.
- **Ids are opaque** to callers: a prefix and hex for records
  (`common/ids.py`), a prefix and encoded JSON for cursors
  (`common/opaque.py`). No caller takes one apart.
- **`SecretStr` for every secret** the moment it is read, so it cannot
  be printed by accident. A secret in plain text is noted with
  `redact`, so it is masked if it ever reaches a line.

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
- The web layer records one activity of its own, a refused request
  body, since the domain never sees that request. It logs nothing else.
- Never in a line: a secret, the words of a mail, a recipient, a search
  term, a body.

## 13. Tests

- A test sits in the folder of the code it tests, `tests/domain/sync/`
  for `domain/sync/`. A test of several layers at once is in
  `tests/integration/`. The fakes and `conftest.py` are at the top.
- Fakes plug in at a seam: the memory provider, `httpx.MockTransport`,
  a fake `IMAPClient` at the imapclient boundary. Nothing is patched
  deep inside a library.
- No test reaches a mail server, and none skips itself without
  credentials. What needs a server is a script in `live/`. What the
  scripts share is in `live/checks/`, one module per subject. What a
  script does with mail on the way goes through the Python client. What
  it asks of the API itself, a status code or an error code, it asks
  with httpx.
- A rule on the layout has a check in `test_architecture.py`, or it is
  not a rule yet: the layers, the lines, the imports through
  `__init__.py`, the homes of the libraries, who logs what. Naming,
  size and style (sections 14 and 15) are for the review.

## 14. Naming

- English, plain words, what a thing is: `AccountService`, `ChangeFeed`,
  `SignInThrottle`. No `Manager`, `Helper`, `Utils`, `Base` unless it
  is one.
- A module is named for its subject (`passwords.py`), not for the
  pattern it uses (`repository.py`).
- A function is a verb (`record`, `forget_account`), a value a noun, a
  boolean a question (`is_public_address`).
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

- A module holds one subject, up to a few hundred lines. Past that, the
  subject has parts, and each part is a module.
- A package holds a handful of modules. Past that, it holds areas, and
  each area is a package.
- A function decides or does, and says which in its name. One that does
  both is two functions.

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
15 is a rule for the review.
