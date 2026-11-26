# Working guidelines for Claude

How to work in this repository. Read this before making changes. See
[docs/mailbox-service/CONCEPT.md](docs/mailbox-service/CONCEPT.md) for what the project is and its API
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
4. **The generated records are the contract.** What a package shows to
   others is a file under `docs/<package>/`, checked in and held to the
   code by a test: the OpenAPI document of the service, the tools of the
   MCP server, the public interface of the client and of the common
   package. After a change to it, regenerate the file with the command
   in that package's CLAUDE.md and review the diff like code.
5. **Secrets never travel.** Provider passwords, OAuth tokens and API tokens
   are never logged, never returned in a response and redacted from error
   text. No real address, credential or message content in any versioned file.
6. **The MCP server is a REST client.** It reaches mail only through the
   REST API, and anything it needs that the API lacks is added to the
   API first. The details: [its CLAUDE.md](packages/mailbox-mcp/CLAUDE.md).
7. **Encapsulate, keep parts replaceable.** Every external library,
   protocol and storage sits behind an interface this project owns, so it
   can be exchanged by rewriting one module. See
   [docs/mailbox-service/ARCHITECTURE.md](docs/mailbox-service/ARCHITECTURE.md).
8. **The repo stands on its own.** No references to the author's other
   repositories, local filesystem paths or email addresses in versioned files.

## The packages

Each package has a CLAUDE.md of its own with the rules that hold for it
alone. Before a change in a package, read its file as well as this one:

- [packages/mailbox-service/CLAUDE.md](packages/mailbox-service/CLAUDE.md):
  the OpenAPI document, the error envelope, paging, migrations, the
  configuration UI and its check in real browsers, the suite against
  PostgreSQL
- [packages/mailbox-mcp/CLAUDE.md](packages/mailbox-mcp/CLAUDE.md): the
  REST client, the tools and their record
- [packages/mailbox-client/CLAUDE.md](packages/mailbox-client/CLAUDE.md):
  the public interface and the requests held to the OpenAPI document
- [packages/mailbox-common/CLAUDE.md](packages/mailbox-common/CLAUDE.md):
  the public interface
- [packages/mailbox-agents/CLAUDE.md](packages/mailbox-agents/CLAUDE.md):
  shadow first, nothing of a mail in a log line, one module per
  upstream, a model without tools, prompts and migrations

## Environment

- Windows, PowerShell or Bash. Python 3.11-3.15. CI measures the
  coverage on the newest and builds the fresh install with it. A new
  version goes into the CI matrix, `coverage-python`, `UV_PYTHON` of
  fresh-install, browser and postgres, the classifiers, the table of
  `docs/mailbox-service/CONCEPT.md` 9 and this line at once, as `test_packaging.py`
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
  for a new page: `docs/mailbox-service/UI.md`.
- Microsoft accounts: the service comes with the project's app,
  `docs/mailbox-service/MICROSOFT.md` also sets up an app of your own. Gmail accounts: a
  Google client of your own, `docs/mailbox-service/GOOGLE.md`.
- A test mail server of our own: `sh containers/test-mail-server/setup.sh`
  makes Stalwart in a container anew, with IMAP, POP3, SMTP and JMAP on
  `127.0.0.1:30xxx`, two accounts and a local test CA
  (`containers/test-mail-server/README.md`).
- A test database of our own: `sh containers/test-database/setup.sh`
  makes PostgreSQL 19 in a container anew on `127.0.0.1:35432`, for the
  suite against PostgreSQL (`containers/test-database/README.md`).
- Live checks: manual scripts in a folder per package under `live/`,
  against the test accounts of
  `live/.env` (not versioned, template `live/.env.example`). What each
  one reads, sends, changes and deletes: [docs/LIVE.md](docs/LIVE.md).
  - `uv run python live/mailbox-service/smoke.py [--show] [--wrong-password]`:
    read-only.
  - `uv run python live/mailbox-service/changes.py [--keep]`: mail between the two test
    accounts, the change feed and a webhook.
  - `MAILBOX_SERVICE_TOKEN=... uv run python live/mailbox-service/register.py
    [--own-service]`: the test accounts in a running service.
  - `uv run python live/mailbox-mcp/mcp_stdio.py` and `live/mailbox-mcp/mcp_http.py`: the MCP
    server over stdio and over streamable HTTP.
  - `uv run python live/mailbox-service/ui.py`: the configuration UI.
  - `uv run python live/mailbox-service/microsoft.py [--connect] [--project] [--large]
    [--marks] [--outbox-draft]`: the Microsoft test account.
  - `uv run python live/mailbox-service/gmail.py [--connect]`: the Gmail test account.
  - `uv run python live/mailbox-service/pop3.py`, `live/mailbox-service/jmap.py` and `live/mailbox-service/imap.py`:
    the test mail server in a container.
  - `uv run python live/mailbox-service/outbox.py [--bots]`: the outbox
    against the test mail server in a container, with `--bots` between
    the first two test accounts as well.
  - `uv run python live/mailbox-service/postgres.py`: PostgreSQL as the
    storage, the move, backup and restore and a stopped database,
    against the test database and the test mail server in containers.
  - `live/mailbox-agents/`: the checks of the agents, against a mail
    server, a service and a model gateway of their own
    ([docs/LIVE.md](docs/LIVE.md#the-agents)).

## Project layout

A uv workspace with five distributions and one lockfile.

```
pyproject.toml            # workspace root: members, dev group, tool config
glama.json                # the GitHub accounts that maintain the MCP
                          #   server's listing on Glama, at the root
                          #   where Glama looks for it
config/                   # one folder per package: .env.example versioned,
                          #   for the agents their example lists too,
                          #   .env and key files local
data/                     # one folder per package, created when missing,
                          #   only .gitkeep is versioned
assets/                   # brand/: the organisation's brand assets,
                          #   icon.svg (the 3D icon) and logo.svg (the
                          #   3D logo) as the sources, icon.png and
                          #   social-preview.png made from them, checked
                          #   by the brand job of the CI. logo/: the
                          #   first files the published releases 0.3.1
                          #   to 0.4.1 still link to, icon-3d.svg from
                          #   the PyPI pages, icon.png from the MCP
                          #   Registry entry of 0.4.1. architecture/:
                          #   the repository README's diagram as HTML
                          #   and PNG, light and dark. build.py makes
                          #   the shipped copies in the service's
                          #   static/img/, with --social the social
                          #   preview, with --diagram the diagrams,
                          #   with --icon brand/icon.png for the MCP
                          #   Registry and the Claude Desktop bundle.
                          #   mailbox-service/, mailbox-client/,
                          #   mailbox-mcp/: architecture/, the diagram
                          #   of each package's README.
                          #   mailbox-service/: icons.py makes the UI's
                          #   icon sprite from a pinned Bootstrap Icons
                          #   package. vendor/: the versions of the
                          #   JavaScript packages the UI ships, a
                          #   package-lock.json for the freshness
                          #   report, nothing installs from it
                          #   (test_vendored.py). mailbox-agents/: the
                          #   agents' own icon and diagram, and their
                          #   build.py that renders them
reports/                  # mailbox-agents/: evaluation reports of the
                          #   agents, numbers only
live/                     # manual checks against the test accounts, a
                          #   folder per package (mailbox-service/,
                          #   mailbox-mcp/, mailbox-agents/) with what
                          #   its scripts share beside them
                          #   (service_common/, mcp_common/,
                          #   agents_common/),
                          #   what all share in common/, one module per
                          #   subject. pyproject.toml installs common/
                          #   into the development environment
containers/               # images/ (one folder per image), and one folder
                          #   per place they run, with a folder per
                          #   package under it: production/ (the
                          #   published images, Caddy, MCP instances),
                          #   development/ (built from the repository),
                          #   live/ (the agents' mail server, service
                          #   and model gateway of their own),
                          #   test-mail-server/ (Stalwart for tests),
                          #   test-database/ (PostgreSQL for tests).
                          #   Each keeps its secrets/ local
.githooks/                # pre-commit: refuses staged settings, keys,
                          #   state files, lines that look like a
                          #   credential and addresses on a domain not
                          #   reserved for examples. Enabled once per
                          #   clone
.github/workflows/        # ci.yml: the organisation's workflows from
                          #   benethos-hub/.github (lint, tests, audit,
                          #   lowest versions per package, coverage
                          #   badge, CodeQL, hadolint, brand assets),
                          #   fresh install, images, the UI in real
                          #   browsers, the storage on PostgreSQL,
                          #   publish.yml: on a release, through the
                          #   organisation's actions, the five packages
                          #   to PyPI, in the order of their dependencies,
                          #   three images to GHCR, the MCP server's
                          #   Claude Desktop bundle onto the release and
                          #   its entry to the MCP Registry. A manual run
                          #   on main tries PyPI and pushes the images as
                          #   edge,
                          #   freshness.yml: daily and after every run of
                          #   publish.yml, what is pinned and what is
                          #   newer, assets/mailbox-service/vendor among it, and whether
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
                          #   the three Dockerfiles, the images of the
                          #   production and test mail server compose
                          #   files by their tags, those of the agents'
                          #   live setup by digest
.github/publish/          # one folder per place a release is listed:
                          #   mcp-registry/server.json, the MCP server's
                          #   entry (test_mcp_registry.py), mcpb/, its
                          #   Claude Desktop bundle (test_mcpb.py)
tests/                    # what the repository holds, across the five
                          #   packages
  test_boundaries.py      # records, not tuples, where a package hands
                          #   values on, in all five
  test_api_names.py       # names the MCP server takes from the API,
                          #   held to docs/mailbox-service/openapi.json
  test_interfaces.py      # docs/mailbox-client/client-interface.json and
                          #   docs/mailbox-common/common-interface.json against the code
  test_code_rules.py      # the rules for the tests of all five
                          #   packages and for live/, no class in a
                          #   package's entry, sizes here and in live/
  test_common_use.py      # how the others use mailbox-common
  test_readmes.py         # the links of every README, of docs/ and of
                          #   every CLAUDE.md lead somewhere, and a README of
                          #   two sections or more lists them in its
                          #   contents at the top, under the 3D icon
  test_module_tree.py     # the trees of docs/mailbox-service/ARCHITECTURE.md section 3
                          #   against the disk, the seams of its
                          #   section 8 against the code
  test_layout.py          # this file's project layout against the disk
  test_repo_content.py    # no tracked file holds a credential, a path
                          #   of a machine, an id of a real record or an
                          #   address on a domain not reserved for
                          #   examples
  test_pre_commit.py      # the hook of .githooks/, held to the same
                          #   lines of credentials and addresses
  test_packaging.py       # the LICENSE copies, the Python versions, one
                          #   version and its examples in the
                          #   documentation
  test_publish.py         # the PyPI jobs of publish.yml, their order and
                          #   the trial run
  test_mcp_registry.py    # the MCP Registry entry held to the package
  test_mcpb.py            # the Claude Desktop bundle held to the package
  test_freshness.py       # the call of freshness.yml
  test_vendored.py        # the lockfile of assets/mailbox-service/vendor held to the
                          #   JavaScript the UI ships
  test_assets.py          # the scripts of assets/: the images made
                          #   from their sources, the diagram, the icon
                          #   sprite
  test_codeql.py          # the calls of CodeQL, every other action by commit
  test_dockerfile_lint.py # the call of hadolint, against every Dockerfile
  installed_check.py      # not a test: the packages as installed, as real
                          #   processes, without an account or a mail
                          #   server, run by hand and by freshness.yml
  interface.py            # not a test: the public interface of a
                          #   package as JSON, for the records in docs/
docs/
  README.md               # the documents of each package, and of the
                          #   repository
  RELEASING.md            # the steps of a release, in order
  ROADMAP.md              # phases and their state
  roadmap/                #   the items of each phase
  IDEAS.md                # collected, not yet decided
  LIVE.md                 # the live checks: what each one reads,
                          #   sends, changes and deletes
  REFACTORING.md          # how the code got its layout, 2026-09 to
                          #   2026-10: what was decided, and the reasons
  mailbox-service/        # the service, and what holds for every package
    CONCEPT.md            # design: the overview and where each section is
    concept/              #   one file per topic, the sections under
                          #   their numbers
    ARCHITECTURE.md       # the shape, the layers, where a piece of code
                          #   goes, and where each section is
    architecture/         #   the modules of the service (section 3)
                          #   and the rules (sections 5 to 17)
    LIMITS.md             # every rate limit and how they work together
    PERMISSIONS.md        # users, roles and rights
    LOGGING.md            # what the service log holds, at which level,
                          #   the rules for a line
    logging/              #   every activity, and where they live in
                          #   the code
    AUDIT.md              # the audit of administration
    UI.md                 # the goals, the rules for a page, the new page
                          #   checklist, and where each section is
    ui/                   #   the pages, the workflows, the look
    MICROSOFT.md          # connecting Microsoft accounts, an app of your own
    GOOGLE.md             # connecting Gmail accounts, the Google client
    AUTHENTICATION.md     # the factors of the UI sign-in: password,
                          #   TOTP, passkeys, and where each section is
    authentication/       #   the methods and the sign-in, devices and
                          #   recovery codes, where it lives in the
                          #   service
    UNIFORM.md            # one way to operate every mailbox: the
                          #   principle, the rules, the capabilities
    uniform/              #   what still differs per provider,
                          #   the decisions, the UI and the MCP server
    openapi.json          # generated, checked in, guarded by a test
  mailbox-mcp/
    CONCEPT.md            # the MCP server, CONCEPT 8 and 8.1
    ARCHITECTURE.md       # its modules, ARCHITECTURE 3.3
    mcp-tools.json        # the MCP server's tools as a client lists them,
                          #   generated, checked in, guarded by a test
  mailbox-client/
    CONCEPT.md            # the Python client, CONCEPT 8.2
    ARCHITECTURE.md       # its modules, ARCHITECTURE 3.2
    client-interface.json # the public interface of mailbox-client,
                          #   generated, checked in, guarded by a test
  mailbox-common/
    ARCHITECTURE.md       # its modules, ARCHITECTURE 3.4
    common-interface.json # the same for mailbox-common
  mailbox-agents/         # the agents, sections of their own
    CONCEPT.md            # the overview, concept/ one file per topic
    concept/              #   and per agent
    ARCHITECTURE.md       # the layers and modules of the agents
    LOGGING.md            # every activity of the agents' log
packages/
  mailbox-service/            # the service, runs permanently
    CLAUDE.md             # the service's own rules
    src/benethos_mailbox_service/   # layers and modules: docs/mailbox-service/ARCHITECTURE.md
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
      test_openapi.py       # docs/mailbox-service/openapi.json equals the code's
      test_cli.py           # the command line
      test_errors.py        # the errors every layer raises
      test_logs.py          # the log of serve: what reaches it, in
                            #   which form
      browser/              # the UI in Chrome, Firefox and WebKit,
                            #   a suite of its own (Verifying)
  mailbox-client/         # the Python client of the REST API, async and
                          #   sync, no image
    CLAUDE.md             # the client's own rules
    src/benethos_mailbox_client/    # modules: docs/mailbox-client/ARCHITECTURE.md
    tests/                # REST mocked with httpx.MockTransport, each
                          #   test for both clients, in files like
                          #   the modules, endpoints/ and models/
                          #   for the packages
  mailbox-mcp/            # the MCP server, on top of mailbox-client
    CLAUDE.md             # the MCP server's own rules
    src/benethos_mailbox_mcp/       # modules: docs/mailbox-mcp/ARCHITECTURE.md
    tests/                # REST mocked with httpx.MockTransport
  mailbox-common/         # what the service, the MCP server and the
                          #   agents share, no image
    CLAUDE.md             # the common package's own rules
    src/benethos_mailbox_common/    # groups, one per concern:
                          #   docs/mailbox-common/ARCHITECTURE.md
    tests/                # in folders like the groups
  mailbox-agents/         # small AI agents on a mailbox, on top of
                          #   mailbox-client, alpha
    CLAUDE.md             # the agents' own rules
    src/benethos_mailbox_agents/    # layers and modules:
                          #   docs/mailbox-agents/ARCHITECTURE.md
    tests/                # in folders like the source, the service and
                          #   the gateway mocked with
                          #   httpx.MockTransport
```

## Architecture

The layers, what each package and module holds, the seams that keep
parts replaceable, and the rules for a new piece of code:
[docs/mailbox-service/ARCHITECTURE.md](docs/mailbox-service/ARCHITECTURE.md). Read it before a change
that adds a module, a package, a library or a seam. The agents have
their own: [docs/mailbox-agents/ARCHITECTURE.md](docs/mailbox-agents/ARCHITECTURE.md).

## Verifying

- Tests: `uv run pytest -q` (offline, must stay green). A test sits in
  the folder of the code it tests, in the service
  `packages/mailbox-service/tests/domain/mailbox/` for its
  `domain/mailbox/`, also when it goes through the API. A test that
  checks several layers at once, such as a backup through the command
  line down to the database file, goes to that package's
  `tests/integration/`.
  The tests run on up to eight processes (pytest-xdist, `addopts` in
  `pyproject.toml`). `-n 0` runs them in one, e.g. for a debugger or
  `-s`.
- Coverage floor 80%: `uv run pytest --cov --cov-fail-under=80`.
- Lint and format: `uv run ruff check .` and `uv run ruff format .`.
- Types: `uv run mypy`.
- Lockfile: `uv lock --check`.
- The UI in real browsers, the one check that runs its JavaScript: the
  service's [CLAUDE.md](packages/mailbox-service/CLAUDE.md). The default
  run leaves it out, CI's browser job runs it.
- The storage on PostgreSQL: the service's
  [CLAUDE.md](packages/mailbox-service/CLAUDE.md). The default run
  leaves it out as well, CI's postgres job runs it.

Never write a test that reaches a real mail server, and never one that skips
itself without credentials. Live checks are manual scripts in `live/`, outside
`testpaths` ([docs/LIVE.md](docs/LIVE.md)). Only the accounts listed in
`live/.env`, and the account `containers/live/mailbox-agents/` makes for
the agents, count as confirmed test accounts for golden rule 1.

## Conventions

- Type hints everywhere, `from __future__ import annotations` at the top.
- `CHANGELOG.md` gets an entry under `[Unreleased]` in the same commit as the
  change, written for someone using the API.
- A decision from a conversation stands in a versioned file in words of
  its own, in English, with its date. Never the user's wording, in no
  language, and never who proposed what.

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
- The pre-commit hook in `.githooks/` refuses staged settings, keys and
  state files, staged lines that look like a credential, and
  addresses on a domain other than those reserved for examples and
  tests (RFC 2606, RFC 6761). Examples here use `example.org` and
  `.example`. It is enabled once per clone with `git config core.hooksPath .githooks`.
  `tests/test_repo_content.py` holds every tracked file to the same
  patterns, in CI as well, where the hook does not run. A line that must
  show such a form ends with `pragma: allowlist secret`.
- End commit messages with
  `Co-Authored-By: Claude Opus 5.5 <noreply@anthropic.com>`.

## Releasing

A release is its own `release/X.Y.Z` branch and pull request. The five
packages carry the same version. The MCP server pins the client and the
common package to it, the service the common package, the agents the
client and the common package.

The steps in order, from the pins to what is checked after the
publish: [docs/RELEASING.md](docs/RELEASING.md).
