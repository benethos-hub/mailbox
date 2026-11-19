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
   Likewise `docs/mcp-tools.json` holds the MCP server's tools as a client
   lists them. After any change to a tool, regenerate it with
   `uv run benethos-mailbox-mcp --list-tools > docs/mcp-tools.json` and
   review the diff of its descriptions like code. And
   `docs/client-interface.json` and `docs/common-interface.json` hold the
   public interface of the two libraries others import. After any change
   to a name, a signature, a field or a default there, regenerate them
   with `uv run python tests/interface.py benethos_mailbox_client >
   docs/client-interface.json`, the same with `benethos_mailbox_common`,
   and review the diff like code: a removed or changed name breaks
   whoever imports it. The client's requests are held to
   `docs/openapi.json` as well, their paths, parameters and bodies.
5. **Secrets never travel.** Provider passwords, OAuth tokens and API tokens
   are never logged, never returned in a response and redacted from error
   text. No real address, credential or message content in any versioned file.
6. **The MCP server is a REST client.** It reaches mail only through the REST
   API, with the client package `mailbox-client`, in packages that cannot
   see the service. Anything the MCP server needs that the API lacks is
   added to the API first.
7. **Encapsulate, keep parts replaceable.** Every external library,
   protocol and storage sits behind an interface this project owns, so it
   can be exchanged by rewriting one module. See
   [docs/ARCHITECTURE.md](docs/ARCHITECTURE.md).
8. **The repo stands on its own.** No references to the author's other
   repositories, local filesystem paths or email addresses in versioned files.

## Environment

- Windows, PowerShell or Bash. Python 3.11-3.15. CI measures the
  coverage on the newest and builds the fresh install with it. A new
  version goes into the CI matrix, `coverage-python`, `UV_PYTHON` of
  fresh-install and browser, the classifiers, the table of
  `docs/CONCEPT.md` 9 and this line at once, as `test_packaging.py`
  checks.
- Set up: `uv sync` (the workspace dev group holds pytest, ruff, mypy).
- Configuration: one folder per package under `config/`, e.g.
  `config/benethos-mailbox-service/.env` (not versioned) beside its
  `.env.example`. Paths count from the repository root, where `uv run` is
  started. Data likewise, one folder per package under `data/` (not
  versioned): the database in `data/benethos-mailbox-service/`. Every
  command of the service takes `--env-file PATH` (or
  `MAILBOX_SERVICE_ENV_FILE`) for a settings file elsewhere. Relative
  paths in it then count from its folder. Installed without the
  repository, the service uses the folders of the operating system
  instead (CONCEPT 7.4). `uv run benethos-mailbox-service paths` names
  what applies. The tests never read or write those folders.
- Run the service: once `uv run benethos-mailbox-service keys init` and
  `uv run benethos-mailbox-service users create-admin` (prints a one-time
  password), then `uv run benethos-mailbox-service serve`. Sign in at
  `http://127.0.0.1:8080/ui` as `admin`, choose a password, and make a
  token on the user's page for the API (`/docs`).
- Run the MCP server: `MAILBOX_SERVICE_TOKEN=... uv run benethos-mailbox-mcp`
  (stdio, `--transport streamable-http` for HTTP).
  For Claude Code and Claude Desktop see `packages/mailbox-mcp/README.md`.
- The configuration UI: `http://127.0.0.1:8080/ui`, sign in with a user
  name and a password. How the pages look and behave, and the checklist
  for a new page: `docs/UI.md`.
- Microsoft accounts: the service comes with the project's app,
  `docs/MICROSOFT.md` also sets up an app of your own. Gmail accounts: a
  Google client of your own, `docs/GOOGLE.md`.
- A test mail server of our own: `sh containers/test-mail-server/setup.sh`
  makes Stalwart in a container anew, with IMAP, POP3, SMTP and JMAP on
  `127.0.0.1:30xxx`, two accounts and a local test CA
  (`containers/test-mail-server/README.md`).
- Live checks: manual scripts in `live/`, against the test accounts of
  `live/.env` (not versioned, template `live/.env.example`). What each
  one reads, sends, changes and deletes: [docs/LIVE.md](docs/LIVE.md).
  - `uv run python live/smoke.py [--show] [--wrong-password]`:
    read-only.
  - `uv run python live/changes.py [--keep]`: mail between the two test
    accounts, the change feed and a webhook.
  - `MAILBOX_SERVICE_TOKEN=... uv run python live/register.py
    [--own-service]`: the test accounts in a running service.
  - `uv run python live/mcp_stdio.py` and `live/mcp_http.py`: the MCP
    server over stdio and over streamable HTTP.
  - `uv run python live/ui.py`: the configuration UI.
  - `uv run python live/microsoft.py [--connect] [--project] [--large]
    [--marks]`: the Microsoft test account.
  - `uv run python live/gmail.py [--connect]`: the Gmail test account.
  - `uv run python live/pop3.py` and `live/jmap.py`: the test mail
    server in a container.

## Project layout

A uv workspace with four distributions and one lockfile.

```
pyproject.toml            # workspace root: members, dev group, tool config
glama.json                # the GitHub accounts that maintain the MCP
                          #   server's listing on Glama, at the root
                          #   where Glama looks for it
config/                   # one folder per package: .env.example versioned,
                          #   .env and key files local
data/                     # one folder per package, created when missing,
                          #   only .gitkeep is versioned
assets/                   # brand/: the organisation's brand assets,
                          #   icon.svg (the 3D icon) and logo.svg (the
                          #   3D logo) as the sources, icon.png and
                          #   social-preview.png made from them, checked
                          #   by the brand job of the CI. logo/: the
                          #   files as they came first. architecture/:
                          #   the README's diagram as HTML and PNG,
                          #   light and dark. build.py makes the
                          #   shipped copies in the service's
                          #   static/img/, with --social the social
                          #   preview, with --diagram the diagram,
                          #   with --icon brand/icon.png for the MCP
                          #   Registry and the Claude Desktop bundle.
                          #   icons.py makes the UI's icon sprite
                          #   from a pinned Bootstrap Icons package.
                          #   vendor/: the versions of the JavaScript
                          #   packages the UI ships, a package-lock.json
                          #   for the freshness report, nothing installs
                          #   from it (test_vendored.py)
live/                     # manual checks against the test accounts,
                          #   what they share in live/checks/, one module
                          #   per subject
containers/               # images/ (one folder per image), and one folder
                          #   per place they run: production/ (the
                          #   published images, Caddy, MCP instances),
                          #   development/ (built from the repository),
                          #   test-mail-server/ (Stalwart for tests).
                          #   Each keeps its secrets/ local
.github/workflows/        # ci.yml: the organisation's workflows from
                          #   benethos-hub/.github (lint, tests, audit,
                          #   lowest versions per package, coverage
                          #   badge, CodeQL, hadolint, brand assets),
                          #   fresh install, images, the UI in real
                          #   browsers,
                          #   publish.yml: on a release, through the
                          #   organisation's actions, the four packages
                          #   to PyPI, in the order of their dependencies,
                          #   both images to GHCR, the MCP server's
                          #   Claude Desktop bundle onto the release and
                          #   its entry to the MCP Registry. A manual run
                          #   on main tries PyPI and pushes the images as
                          #   edge,
                          #   freshness.yml: daily and after every run of
                          #   publish.yml, what is pinned and what is
                          #   newer, assets/vendor among it, and whether
                          #   the newest versions
                          #   allowed and the published packages still
                          #   work, two issues through the organisation's
                          #   reusable workflow,
                          #   codeql.yml: weekly, the codeql job of ci.yml
                          #   once more, for the queries GitHub adds
.github/codeql/           # codeql-config.yml: the rules of CodeQL left out,
                          #   each with its reason
.github/dependabot.yml    # weekly, minor and patch grouped: uv.lock, with
                          #   the ranges kept while they allow the release,
                          #   the actions by commit, the base images of
                          #   both Dockerfiles
.github/publish/          # one folder per place a release is listed:
                          #   mcp-registry/server.json, the MCP server's
                          #   entry (test_mcp_registry.py), mcpb/, its
                          #   Claude Desktop bundle (test_mcpb.py)
tests/                    # what the repository holds, across the four
                          #   packages
  test_boundaries.py      # records, not tuples, where a package hands
                          #   values on, in all four
  test_api_names.py       # names the MCP server takes from the API,
                          #   held to docs/openapi.json
  test_interfaces.py      # docs/client-interface.json and
                          #   docs/common-interface.json against the code
  test_code_rules.py      # the rules for the tests of all four
                          #   packages and for live/, no class in a
                          #   package's entry, sizes here and in live/,
                          #   how the others use mailbox-common
  test_readmes.py         # the links of every README, of docs/ and of
                          #   this file lead somewhere, and a README of
                          #   two sections or more lists them in its
                          #   contents at the top, under the 3D icon
  test_module_tree.py     # the trees of docs/ARCHITECTURE.md section 3
                          #   against the disk, the seams of its
                          #   section 8 against the code
  test_layout.py          # this file's project layout against the disk
  test_packaging.py       # the LICENSE copies, the Python versions, one
                          #   version and its examples in the
                          #   documentation
  test_publish.py         # the PyPI jobs of publish.yml, their order and
                          #   the trial run
  test_mcp_registry.py    # the MCP Registry entry held to the package
  test_mcpb.py            # the Claude Desktop bundle held to the package
  test_freshness.py       # the call of freshness.yml
  test_vendored.py        # the lockfile of assets/vendor held to the
                          #   JavaScript the UI ships
  test_codeql.py          # the calls of CodeQL, every other action by commit
  test_dockerfile_lint.py # the call of hadolint, against every Dockerfile
  installed_check.py      # not a test: the packages as installed, as real
                          #   processes, without an account or a mail
                          #   server, run by hand and by freshness.yml
  interface.py            # not a test: the public interface of a
                          #   package as JSON, for the records in docs/
docs/
  CONCEPT.md              # design: the overview and where each section is
  concept/                #   one file per topic, the sections under
                          #   their numbers
  ARCHITECTURE.md         # the shape, the layers, where a piece of code
                          #   goes, and where each section is
  architecture/           #   the modules of the four packages (section
                          #   3) and the rules (sections 5 to 17)
  LIMITS.md               # every rate limit and how they work together
  PERMISSIONS.md          # users, roles and rights
  LOGGING.md              # what the service log holds, at which level,
                          #   the rules for a line
  logging/                #   every activity, and where they live in
                          #   the code
  AUDIT.md                # the audit of administration
  UI.md                   # the goals, the rules for a page, the new page
                          #   checklist, and where each section is
  ui/                     #   the pages, the workflows, the look
  REFACTORING.md          # how the layout came to be: what was
                          #   decided, and the reasons
  MICROSOFT.md            # connecting Microsoft accounts, an app of your own
  GOOGLE.md               # connecting Gmail accounts, the Google client
  AUTHENTICATION.md       # the factors of the UI sign-in: password,
                          #   TOTP, passkeys
  UNIFORM.md              # one way to operate every mailbox: the
                          #   principle, the rules, the capabilities
  uniform/                #   what still differs per provider,
                          #   the decisions, the UI and the MCP server
  LIVE.md                 # the live checks: what each one reads,
                          #   sends, changes and deletes
  RELEASING.md            # the steps of a release, in order
  ROADMAP.md              # phases and their state
  roadmap/                #   the items of each phase
  IDEAS.md                # collected, not yet decided
  openapi.json            # generated, checked in, guarded by a test
  mcp-tools.json          # the MCP server's tools as a client lists them,
                          #   generated, checked in, guarded by a test
  client-interface.json   # the public interface of mailbox-client and
  common-interface.json   #   of mailbox-common, generated, checked in,
                          #   guarded by a test
packages/
  mailbox-service/            # the service, runs permanently
    src/benethos_mailbox_service/   # layers and modules: docs/ARCHITECTURE.md
    tests/                # in folders like the source: domain/<package>/,
                          #   data/, web/, common/. integration/ for tests
                          #   of several layers at once. At the top the
                          #   fakes, conftest.py and what checks the whole
                          #   service
      test_architecture.py  # checks the layering on every run
      test_packages.py      # the packages of the domain and of data:
                            #   through __init__.py, no cycle, their lines
      test_assembly.py      # the assembly and the command line keep
                            #   their lines
      test_code_rules.py    # logging, handlers, sizes, helpers once,
                            #   htmx in one module, the tests of the
                            #   data layer
      test_openapi.py       # docs/openapi.json equals the code's
      test_cli.py           # the command line
      test_errors.py        # the errors every layer raises
      test_logs.py          # the log of serve: what reaches it, in
                            #   which form
      browser/              # the UI in Chrome, Firefox and WebKit,
                            #   a suite of its own (Verifying)
  mailbox-client/         # the Python client of the REST API, async and
                          #   sync, no image
    src/benethos_mailbox_client/    # modules: docs/ARCHITECTURE.md
    tests/                # REST mocked with httpx.MockTransport, each
                          #   test for both clients, in files like
                          #   the modules, endpoints/ and models/
                          #   for the packages
  mailbox-mcp/            # the MCP server, on top of mailbox-client
    src/benethos_mailbox_mcp/       # modules: docs/ARCHITECTURE.md
    tests/                # REST mocked with httpx.MockTransport
  mailbox-common/         # what the service and the MCP server share,
                          #   no image
    src/benethos_mailbox_common/    # groups, one per concern:
                          #   docs/ARCHITECTURE.md
    tests/                # in folders like the groups
```

## Architecture

The layers, what each package and module holds, the seams that keep
parts replaceable, and the rules for a new piece of code:
[docs/ARCHITECTURE.md](docs/ARCHITECTURE.md). Read it before a change
that adds a module, a package, a library or a seam.

## Verifying

- Tests: `uv run pytest -q` (offline, must stay green). A test sits in
  the folder of the code it tests, `tests/domain/mailbox/` for
  `domain/mailbox/`, also when it goes through the API. A test that
  checks several layers at once, such as a backup through the command
  line down to the database file, goes to `tests/integration/`.
- Coverage floor 80%: `uv run pytest --cov --cov-fail-under=80`.
- Lint and format: `uv run ruff check .` and `uv run ruff format .`.
- Types: `uv run mypy`.
- Lockfile: `uv lock --check`.
- The UI in real browsers, the one check that runs its JavaScript:
  `uv run --group browser playwright install chromium firefox webkit`
  once, then `MAILBOX_BROWSER_TESTS=1 uv run --group browser pytest
  packages/mailbox-service/tests/browser`. The sign-in with a code must
  go on by itself through htmx, and no page reached from the overview
  may break the content security policy or miss a file of its own. In
  Chromium a passkey is made on the page Second factor and signs in,
  through its virtual authenticator. The
  default run leaves the folder out, CI's browser job runs it. Run it
  after a change to a template, to `static/` or to htmx.

Never write a test that reaches a real mail server, and never one that skips
itself without credentials. Live checks are manual scripts in `live/`, outside
`testpaths` ([docs/LIVE.md](docs/LIVE.md)). Only the accounts listed in
`live/.env` count as confirmed test accounts for golden rule 1.

## Conventions

- Type hints everywhere, `from __future__ import annotations` at the top.
- Every error response uses the envelope `{"error": {"code", "message"}}`.
- Lists are paged with an opaque `next_cursor`, never with page numbers.
- `CHANGELOG.md` gets an entry under `[Unreleased]` in the same commit as the
  change, written for someone using the API.
- A change to the database schema is a new migration: a class
  `VNNNN<Subject>` of the base `Migration` in a module
  `vNNNN_<subject>.py` in `data/storage/sqlite/migrations/versions/` with
  the next number, added to the registry `MIGRATIONS` in
  `migrations/__init__.py`. The module's docstring says what it
  does and why. Each statement stands alone, and a step in Python is the
  method `before`. A migration that shipped in a release is never changed:
  `RELEASED` in
  `packages/mailbox-service/tests/data/storage/test_sqlite.py` holds the fingerprint
  of each.

## Git and commits

- Commit only when the user asks. Clear, descriptive messages.
- `main` is protected: no direct push, no force push, a linear history,
  and every CI job but `coverage-badge`, `codeql`, `dockerfile-lint` and
  `browser` must pass. Most are the organisation's reusable workflows, named
  `<job> / <name>`, such as `test / Python 3.15`, `lowest-mcp / Python 3.11`,
  `audit / Dependency audit` and `brand / Brand assets`. `codeql` and
  `dockerfile-lint` file what they find under Security, Code scanning, and a
  merge does not wait for them, nor for `browser`, the UI in real browsers.
  Every change reaches `main` as a pull request.
- The flow: a branch per work stream, created before the first edit.
  Commit, push the branch, open the pull request with `gh pr create`.
  The user merges it on GitHub as a squash merge. Afterwards pull `main`
  with `git pull --ff-only` and delete the local branch.
- Dependabot opens its own pull requests. The user merges them as well.
- End commit messages with
  `Co-Authored-By: Claude Opus 5.5 <noreply@anthropic.com>`.

## Releasing

A release is its own `release/X.Y.Z` branch and pull request. The four
packages carry the same version. The MCP server pins the client and the
common package to it, the service the common package.

The steps in order, from the pins to what is checked after the
publish: [docs/RELEASING.md](docs/RELEASING.md).
