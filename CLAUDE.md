# Working guidelines for Claude

How to work in this repository. Read this before making changes. See
[docs/CONCEPT.md](docs/CONCEPT.md) for what the project is and its API
design, and [docs/ROADMAP.md](docs/ROADMAP.md) for the phases and what is
done. Update the roadmap in the same commit that finishes an item.

## Golden rules

1. **Real mailboxes, real consequences.** This service reads and sends mail
   from people's accounts. Never send, delete or move mail on an account that
   has not been explicitly confirmed as a test account.
2. **Virtual environment only.** Never the global Python or pip. `uv run ...`
   satisfies this rule. Without uv, use `.\.venv\Scripts\python.exe`.
3. **English in the repo.** Code, comments, docstrings and documentation are
   English. Conversation with the user may be German.
4. **The OpenAPI document is the contract.** `docs/openapi.json` is checked in
   and a test compares it with the code. After any change to a route or model,
   regenerate it with `uv run benethos-mailbox-service openapi > docs/openapi.json`
   and review the diff like code. `operationId` is the route function name and
   must stay stable, since generated clients and the MCP server depend on it.
5. **Secrets never travel.** Provider passwords, OAuth tokens and the API key
   are never logged, never returned in a response and redacted from error
   text. No real address, credential or message content in any versioned file.
6. **The MCP server is a REST client.** It reaches mail only through the REST
   API, in its own package that cannot see the service. Anything the MCP server needs
   that the API lacks is added to the API first.
7. **Encapsulate, keep parts replaceable.** Every external library,
   protocol and storage sits behind an interface this project owns, so it
   can be exchanged by rewriting one module. See "Encapsulation and
   replaceable parts" below.
8. **The repo stands on its own.** No references to the author's other
   repositories, local filesystem paths or email addresses in versioned files.

## Environment

- Windows, PowerShell or Bash. Python 3.11-3.14.
- Set up: `uv sync` (the workspace dev group holds pytest, ruff, mypy).
- Configuration: one folder per package under `config/`, e.g.
  `config/benethos-mailbox-service/.env` (not versioned) beside its
  `.env.example`. Paths count from the repository root, where `uv run` is
  started. Data likewise, one folder per package under `data/` (not
  versioned): the database in `data/benethos-mailbox-service/`.
- Run the service: once `uv run benethos-mailbox-service keys init`, then
  `MAILBOX_SERVICE_KEY=... uv run benethos-mailbox-service serve` and
  `http://127.0.0.1:8080/docs`.
- Live checks: `uv run python live/smoke.py [--show]` (read-only) and
  `uv run python live/changes.py [--keep]` (sends one test mail between the test
  accounts, moves it, deletes it), test accounts in `live/.env` (not
  versioned, template `live/.env.example`).
  `MAILBOX_SERVICE_TOKEN=... uv run python live/register.py` adds the test
  accounts to a running service over its API and checks them.
- Run the MCP server: `MAILBOX_SERVICE_TOKEN=... uv run benethos-mailbox-mcp`
  (stdio, `--transport streamable-http` for HTTP).
  For Claude Code and Claude Desktop see `packages/mailbox-mcp/README.md`.
  `uv run python live/mcp_stdio.py` checks it over stdio against the test
  accounts, with a service and database of its own. The write tools create
  a folder and star, move and trash a message of the first test account,
  then put everything back. The draft tools write, replace and delete a
  reply draft there. The send tools send two mails from the first test
  account to the second and delete them for good. Grants with recipients
  and a send limit stop mails, and the audit names each attempt.
  `uv run python live/mcp_http.py` checks it over streamable HTTP behind
  its bearer token, read-only.
- The configuration UI: `http://127.0.0.1:8080/ui`, sign in with a token.
  `uv run python live/ui.py` checks it against the test accounts. It sends
  one mail from the first test account to the second and deletes it for
  good on both sides.
- Microsoft accounts: `docs/microsoft.md` sets up the app registration.
  `uv run python live/microsoft.py --connect` once (a person signs in in
  the browser), then `uv run python live/microsoft.py` checks the adapter
  against the Microsoft test account in `live/.env`. It sends one mail
  from it to the first test account and deletes it for good on both sides.

## Project layout

A uv workspace with two distributions and one lockfile.

```
pyproject.toml            # workspace root: members, dev group, tool config
config/                   # one folder per package: .env.example versioned,
                          #   .env and key files local
data/                     # one folder per package, created when missing,
                          #   only .gitkeep is versioned
live/                     # manual checks against the test accounts,
                          #   what they share in _common.py
containers/               # one folder per image, compose.yaml, README.md,
                          #   secrets/ local (the master key)
.github/workflows/        # ci.yml: checks, fresh install, lowest
                          #   versions, images,
                          #   publish.yml: on a release both packages to
                          #   PyPI and both images to GHCR
docs/
  CONCEPT.md              # design
  ROADMAP.md              # phases and their state
  IDEAS.md                # collected, not yet decided
  openapi.json            # generated, checked in, guarded by a test
packages/
  mailbox-service/            # the service, runs permanently
    src/benethos_mailbox_service/
      __main__.py         # CLI: serve, openapi, users, keys, backup, restore
      main.py             # assembly only: create_app, picks implementations
      config.py           # cross-cutting: Settings (MAILBOX_SERVICE_* env and
                          #   config/benethos-mailbox-service/.env)
      errors.py           # cross-cutting: MailboxServiceError hierarchy, no HTTP
      common/             # cross-cutting: helpers several layers share,
                          #   standard library only
        ids.py            # ids of own records: acc_, usr_, msg_, ... + 64 hex
        opaque.py         # opaque ids and cursors: prefix + base64 JSON
        clock.py          # utc_now, the default clock of the services
      web/                # PRESENTATION: HTTP only, FastAPI lives here
        __init__.py       # install: both front ends, errors to the right one
        services.py       # the domain services as dependencies, for both
        urls.py           # this service's public address, OAuth callback
        api/              # the JSON API: /health open, the rest under /v1
          deps.py         # bearer authentication, services per request
          schemas.py      # shapes that exist only at the HTTP boundary
          errors.py       # error class -> status code, the error envelope
          routes/         # one router per resource
        pages/            # the configuration UI under /ui, not in OpenAPI
          deps.py         # who is signed in, the CSRF check
          session.py      # sign-in with a token, server-side sessions
          templates.py    # Jinja2: filters, render, Post/Redirect/Get
          grants.py       # the grant editor's rows, read back into grants
          mailform.py     # the mail form: fields to a message, shown again
          forms.py        # form errors, failing: back with the message
          rights.py       # what the mail pages offer, by the rights on an account
          errors.py       # errors as a page
          routes/         # one module per area
          templates/      # base, partials, components (macros), pages
          static/         # app.css, app.js, vendored htmx
      domain/             # BUSINESS LOGIC: decides, knows no HTTP
        accounts.py       # AccountService: accounts under the caller's rights
        adapters.py       # Adapters: the live adapter per account, calls through it
        oauth.py          # OAuthService: connect or sign in again by OAuth
        mailbox.py        # MailboxService: folders and messages, the facade
        calls.py          # provider calls under our stable ids, many at once
        outgoing.py       # sending and drafts, reached through MailboxService
        merge.py          # lists across accounts: merge order, cursor
        replies.py        # replies and forwards made from the original
        discovery.py      # DiscoveryService: trust, ranking, cache, limits
        sync.py           # SyncService: stable message ids, the sync pass
        worker.py         # SyncWorker: polling and IDLE in the background
        idempotency.py    # Idempotency-Key: a retried send returns its result
        locks.py          # KeyedLocks: one asyncio lock per key, for the services
        sending.py        # SendControl: grant constraints on sending, send audit
        permissions.py    # the catalogue of rights and groups
        access.py         # Access: what one caller may do
        auth.py           # AuthService: tokens, the admin key
        throttle.py       # SignInThrottle: a source that fails too often waits
        users.py          # UserService: users, roles, tokens
      data/               # DATA: reads and writes, decides nothing
        models/           # provider-neutral types, one module per subject:
                          #   accounts, users, folders, messages, batch,
                          #   sending, paging, discovery, audit
        mail/             # messages in RFC 5322, whatever protocol carries them
          compose.py      # outgoing messages as bytes (email)
          parse.py        # incoming bytes parsed (imap-tools' mail parser)
          convert.py      # a parsed message to Message / MessageSummary
          text.py         # the text part of an HTML-only mail
          fields.py       # one header field: a Message-ID as one token,
                          #   an address in Unicode
        providers/        # registry in __init__.py (also sign_in), base.py
          protocols/      # wire protocols, one library each: imap.py
                          #   (IMAPClient), smtp.py (smtplib), oauth.py
                          #   (OAuth 2.0 with PKCE, refresh, token source),
                          #   transport.py: the failures below every library
          guard.py        # pacing, retries, blocked logins, for any adapter
          sender.py       # SmtpSender: sending for IMAP, POP3, ...
          imap/, memory/, # one directory per provider (adapter)
          microsoft/      #   microsoft: Graph over data/http, signin.py
                          #   its endpoints and the scopes it needs
        http/             # httpx: base.py (the client, the capped read),
                          #   safe.py (hosts users typed, SSRF guard),
                          #   api.py (JSON to a provider's known hosts)
        storage/          # own records, one module per subject, table.py
                          #   for the in-memory ones, sqlite/ the database
        secrets/          # envelope encryption, key providers, backup
        files.py          # files for the owner alone (0600): database, backup, key
        discovery/        # autodiscovery sources and their helpers
    tests/
      test_architecture.py  # checks the layering on every run
  mailbox-mcp/            # the MCP server, a REST client
    src/benethos_mailbox_mcp/
      server.py           # MCPServer, tools by the token's rights, CLI
      transport.py        # streamable HTTP: bearer guard, host check (uvicorn)
      render.py           # what the model sees of mail, marked as foreign
      pdf.py              # PDF pages as PNG (pypdfium2)
      client.py           # ALL access to the REST API
      errors.py           # ToolError subclasses
    tests/                # REST mocked with httpx.MockTransport
```

## Layers of the service

Three layers, imports only point down: `web/` → `domain/` → `data/`.

| Layer | Directory | Job | May import |
|---|---|---|---|
| Presentation | `web/` | HTTP: check input, call the domain, answer | domain, data |
| Business logic | `domain/` | decide: accounts, rights, id mapping, sync | data |
| Data | `data/` | own records and foreign mail sources | neither |

- `config.py`, `errors.py` and `common/` are cross-cutting: read by every
  layer, they import none. `main.py` and `__main__.py` only assemble.
- **`common/` is not a drawer.** Only stateless helpers that more than one
  layer needs, on the standard library alone. What one layer needs stays in
  that layer.
- **No HTTP in the domain.** Nothing below `web/` raises an HTTP exception or
  knows a status code. The domain raises `errors`, and `web/api/errors.py` maps
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

`tests/test_architecture.py` checks the direction, the cross-cutting
modules, that `common/` stays on the standard library, that FastAPI stays in
`web/` (and `main.py`), and that providers are reached through the registry. An import that breaks a rule fails the suite.

## Encapsulation and replaceable parts

This project is built from parts that can be exchanged one at a time. A
mail library, the database, the web framework or a whole provider should be
replaceable by rewriting **one module**, without the rest of the code
noticing. Every change is measured against that.

**The rules that make it work:**

1. **Our interface, not theirs.** Code depends on interfaces this project
   defines (`MailProvider`, a store protocol, a key provider), never on a
   third-party type. A library's objects, exceptions and quirks do not cross
   the module that wraps it.
2. **One library, one home.** Each external dependency is imported in
   exactly one module or, for a framework, one package: IMAPClient only in
   `protocols/imap.py`, `cryptography` only in the crypto module, FastAPI only
   under `web/`. When you need it somewhere else, extend its wrapper instead
   of importing it a second time. Two deliberate exceptions: pydantic,
   which is how this project writes its own types, and anyio, which is how
   it writes concurrency.
3. **Translate at the edge.** A wrapper maps everything into this project's
   types on the way in (`data/models/`) and every failure into a
   `MailboxServiceError` subclass. Nothing upstream sees a raw library exception
   or response.
4. **Dependencies point inward.** Routes know the store and the models. The
   models know nothing of FastAPI, SQLite or IMAP. The domain never imports
   the layer above it.
5. **Wire it in one place.** Which implementation is used is decided where
   the app is assembled (`create_app`, the account store's factory,
   settings), never inside the code that uses it. That is also how tests
   swap in fakes.
6. **The contract is the boundary.** Between the two packages there is only
   the REST API. The MCP package never depends on or imports the service
   package, and `tests/test_boundary.py` checks both.

**The seams, and what sits behind each:**

| Seam | Defined in | Implementations | Exchangeable for |
|---|---|---|---|
| Mail provider | `data/providers/base.py` (`MailProvider`, `Capability`), registry in `data/providers/__init__.py` | memory, imap, microsoft (planned: gmail, pop3) | another protocol or library, e.g. `aioimaplib` for IMAPClient |
| Sending | `data/providers/protocols/smtp.py` (`SmtpSession`), and `sender.py` (`SmtpSender`), which adapters without sending of their own (IMAP, later POP3) hold | stdlib smtplib | e.g. aiosmtplib |
| Web layer | `web/` | FastAPI, later templates for the UI | another framework, as long as the OpenAPI document stays the same |
| Account and user store | `data/storage/` (`AccountRepository`, `UserRepository`, `RoleRepository`, `TokenRepository`, `KeyRepository`, `CredentialRepository`, `MessageIndexRepository`, `IdempotencyRepository`, `SendLogRepository`) | in-memory, SQLite | another database |
| Autodiscovery source | `data/discovery/` (`DiscoverySource`) | presets, ISP autoconfig, ISPDB, MX (planned: JMAP well-known, Microsoft realm, SRV, guessing) | any further lookup, or one switched off |
| HTTP | `data/http/` (`SafeFetcher`, `ApiClient`) | httpx | another HTTP client |
| OAuth token source | `TokenSource` in `data/providers/base.py`, made in `data/providers/protocols/oauth.py`, each OAuth provider's endpoints and scopes in its own directory, reached through `sign_in` in the registry | refresh token in the vault, access token in memory | another token store |
| Secret encryption | `KeyProvider` in `data/secrets/keys.py` | keyring, file, env | a secret manager such as Vault |
| Authentication | credential kinds of a user (CONCEPT 7.5) | API token | password + TOTP, OAuth client credentials |
| MCP ↔ service | the REST API, `docs/openapi.json` | httpx client in `client.py` | a generated client |

**When you add something new**, ask first where its seam is. A new
provider is a new module behind `MailProvider`, not a branch in a route. A
new library gets a wrapper before it gets a caller. If a change needs edits
in several layers to swap one technology, the seam is in the wrong place:
fix that first, and say so.

**Tests use the seams too.** Fakes are plugged in at an interface (the
memory provider, `httpx.MockTransport`, a fake `IMAPClient` at the
imapclient boundary), never by patching deep inside a library.

## Verifying

- Tests: `uv run pytest -q` (offline, must stay green).
- Coverage floor 80%: `uv run pytest --cov --cov-fail-under=80`.
- Lint and format: `uv run ruff check .` and `uv run ruff format .`.
- Types: `uv run mypy`.
- Lockfile: `uv lock --check`.

Never write a test that reaches a real mail server, and never one that skips
itself without credentials. Live checks are manual scripts in `live/`, outside
`testpaths`.
They run against test accounts on an IMAP server of our own. Its address
and the list of test accounts are local, unversioned configuration, and
only the accounts listed there count as confirmed test accounts for golden
rule 1.

## Conventions

- Type hints everywhere, `from __future__ import annotations` at the top.
- Every error response uses the envelope `{"error": {"code", "message"}}`.
- Lists are paged with an opaque `next_cursor`, never with page numbers.
- `CHANGELOG.md` gets an entry under `[Unreleased]` in the same commit as the
  change, written for someone using the API.

## Git and commits

- Commit only when the user asks. Clear, descriptive messages.
- `main` is protected: no direct push, no force push, a linear history,
  and every CI job but `lowest-versions` must pass. Every change reaches
  `main` as a pull request.
- The flow: a branch per work stream, created before the first edit.
  Commit, push the branch, open the pull request with `gh pr create`.
  The user merges it on GitHub as a squash merge. Afterwards pull `main`
  with `git pull --ff-only` and delete the local branch.
- Dependabot opens its own pull requests. The user merges them as well.
- End commit messages with
  `Co-Authored-By: Claude Opus 5.5 <noreply@anthropic.com>`.

## Releasing

A release is its own `release/X.Y.Z` branch and pull request. Both
packages carry the same version.

1. `uv lock --upgrade --dry-run`. If it moves anything, run
   `uv lock --upgrade` as a commit of its own, then all checks.
2. Set `version` in both packages' `pyproject.toml`, then `uv lock` and
   `uv sync`. `test_packaging.py` names every version example in the
   documentation that still shows the old one.
3. Close `[Unreleased]` in `CHANGELOG.md` as `[X.Y.Z] - <date>`.
4. After the squash merge: an annotated tag `vX.Y.Z` on `main`, pushed,
   then `gh release create vX.Y.Z --verify-tag` with the changelog section
   as the notes. The published release starts `publish.yml`, which
   uploads both packages to PyPI and both images to GHCR.
5. Check what shipped: both packages on PyPI, and each image's tags
   `X.Y.Z`, `X.Y` and `latest` on the same revision.
