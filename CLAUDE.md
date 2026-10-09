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

- Windows, PowerShell or Bash. Python 3.11-3.14.
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
- Live checks: `uv run python live/smoke.py [--show] [--wrong-password]`
  (read-only) and
  `uv run python live/changes.py [--keep]` (sends one test mail from the
  second test account to the first, flags and moves it, replies,
  forwards and sends a draft back to the second, makes and removes a
  folder, deletes it all for good, and checks the change feed and a
  webhook on a receiver at 127.0.0.1), test accounts in `live/.env` (not
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
  reply draft there. The send tools send three mails from the first test
  account to the second, one of them twice with the same call and one
  from a draft, and delete them for good. Grants with recipients
  and a send limit stop mails, and the audit names each attempt.
  `whats_new` must name the changes of the write tools.
  `uv run python live/mcp_http.py` checks it over streamable HTTP behind
  its bearer token, read-only.
- The configuration UI: `http://127.0.0.1:8080/ui`, sign in with a user
  name and a password. The live checks with a service of their own make
  its first user with `users create-admin`, change the one-time password
  in the UI and make a token there, as an operator would.
  `uv run python live/ui.py` checks it against the test accounts. It
  connects the second test account through the UI, writes a folder and
  a draft on the first and removes them, and sends one mail from the
  first to the second, deleted for good on both sides. It also makes a
  user, a role and a token and uses the token on the API, opens the
  status, adds and removes a webhook, shows the recovery key of its own
  service, reads its log, makes a user with a one-time password and
  reads the audit of administration. A user of its own adds two devices
  of the second factor's first method, TOTP, from the keys of their QR
  codes, renames one, signs in with a code of each and a recovery code,
  and has them removed by itself, the admin and the host.
  How the pages look and behave, and the checklist for a new page:
  `docs/UI.md`.
- Microsoft accounts: the service comes with the project's app,
  `docs/MICROSOFT.md` also sets up an app of your own.
  `uv run python live/microsoft.py --connect` once (a person signs in in
  the browser), then `uv run python live/microsoft.py` checks the adapter
  against the Microsoft test account in `live/.env` with that app. With
  `--project` both use the project's app: `--connect` prints a code a
  person enters at Microsoft. It makes and removes a folder and a reply
  draft there, sends one mail from it to the first test account and
  deletes it for good on both sides, and checks that the change feed
  learns of the sent copy through Graph delta queries.
- Gmail accounts: a Google client of your own, `docs/GOOGLE.md`.
  `uv run python live/gmail.py --connect` once (a person signs in in
  the browser), then `uv run python live/gmail.py` checks the adapter
  against the Gmail test account in `live/.env` with that client. It
  makes a label inside a label, renames and removes them, writes,
  replaces and deletes a draft, sends one mail from it to the first
  test account, deleted for good there, stars, labels and archives the
  copy in Sent, deletes it for good, and checks that the change feed
  learns of it through Gmail's history. Then the first test account
  sends one mail to it, which must arrive in the inbox, be found, open
  and turn read, and is deleted for good on both sides.
- A test mail server of our own: `sh containers/test-mail-server/setup.sh`
  makes Stalwart in a container anew, with IMAP, POP3, SMTP and JMAP on
  `127.0.0.1:30xxx`, two accounts and a local test CA
  (`containers/test-mail-server/README.md`). `uv run python live/pop3.py`
  checks the POP3 adapter against it: one mail from the first account to
  the second, read, found by the sync and deleted for good.
  `uv run python live/jmap.py` checks the JMAP adapter against it, with a
  service of its own as a process: one mail from the first account to the
  second, reported by push, changed, put in a folder and back, a draft,
  then deleted for good on both sides.
## Project layout

A uv workspace with four distributions and one lockfile.

```
pyproject.toml            # workspace root: members, dev group, tool config
config/                   # one folder per package: .env.example versioned,
                          #   .env and key files local
data/                     # one folder per package, created when missing,
                          #   only .gitkeep is versioned
assets/                   # logo/: the logo and the icon as they came,
                          #   and the social preview. architecture/:
                          #   the README's diagram as HTML and PNG,
                          #   light and dark. build.py makes the
                          #   shipped copies in the service's
                          #   static/img/, with --social the social
                          #   preview, with --diagram the diagram.
                          #   icons.py makes the UI's icon sprite
                          #   from a pinned Bootstrap Icons package
live/                     # manual checks against the test accounts,
                          #   what they share in live/checks/, one module
                          #   per subject
containers/               # images/ (one folder per image), and one folder
                          #   per place they run: production/ (the
                          #   published images, Caddy, MCP instances),
                          #   development/ (built from the repository),
                          #   test-mail-server/ (Stalwart for tests).
                          #   Each keeps its secrets/ local
.github/workflows/        # ci.yml: checks, fresh install, lowest
                          #   versions, images,
                          #   publish.yml: on a release the four packages
                          #   to PyPI, in the order of their dependencies,
                          #   and both images to GHCR
.github/actions/          # pypi-package/: the steps of one upload to PyPI
docs/
  CONCEPT.md              # design
  ARCHITECTURE.md         # layers, modules, seams, rules for new code
  LIMITS.md               # every rate limit and how they work together
  PERMISSIONS.md          # users, roles and rights
  LOGGING.md              # what the service log holds, at which level
  AUDIT.md                # the audit of administration
  UI.md                   # how the pages look and behave, new page checklist
  REFACTORING.md          # how the layout came to be
  MICROSOFT.md            # connecting Microsoft accounts, an app of your own
  GOOGLE.md               # connecting Gmail accounts, the Google client
  AUTHENTICATION.md       # the factors of the UI sign-in: password, TOTP
  ROADMAP.md              # phases and their state
  IDEAS.md                # collected, not yet decided
  openapi.json            # generated, checked in, guarded by a test
packages/
  mailbox-service/            # the service, runs permanently
    src/benethos_mailbox_service/   # layers and modules: docs/ARCHITECTURE.md
    tests/                # in folders like the source: domain/<package>/,
                          #   data/, web/, common/. integration/ for tests
                          #   of several layers at once. At the top the
                          #   fakes, conftest.py and what checks the whole
                          #   service
      test_architecture.py  # checks the layering on every run
      test_code_rules.py    # logging, handlers, sizes, helpers once
  mailbox-client/         # the Python client of the REST API, async and
                          #   sync, no image
    src/benethos_mailbox_client/    # modules: docs/ARCHITECTURE.md
    tests/                # REST mocked with httpx.MockTransport, each
                          #   test for both clients, in files like
                          #   the modules, endpoints/ for the package
  mailbox-mcp/            # the MCP server, on top of mailbox-client
    src/benethos_mailbox_mcp/       # modules: docs/ARCHITECTURE.md
    tests/                # REST mocked with httpx.MockTransport
  mailbox-common/         # what the service and the MCP server share,
                          #   no image
    src/benethos_mailbox_common/    # modules: docs/ARCHITECTURE.md
    tests/                # in files like the modules
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

Never write a test that reaches a real mail server, and never one that skips
itself without credentials. Live checks are manual scripts in `live/`, outside
`testpaths`.
They run against test accounts: on an IMAP server of our own, the
Microsoft test account, and the test mail server in a container. The
server's address and the list of test accounts are local, unversioned
configuration, and only the accounts listed there count as confirmed
test accounts for golden rule 1.

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
  `RELEASED` in `tests/data/storage/test_sqlite.py` holds the fingerprint
  of each.

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

A release is its own `release/X.Y.Z` branch and pull request. The four
packages carry the same version. The MCP server pins the client and the
common package to it, the service the common package.

Once, before the first release with `mailbox-common`: the user adds on
PyPI the pending publisher of the project `benethos-mailbox-common`
(this repository, `publish.yml`, environment
`pypi-benethos-mailbox-common`), and on GitHub that environment.
Without it the upload of common fails, and the client, the service and
the MCP server wait for it in vain. Remove this paragraph after that
release.

1. `uv lock --upgrade --dry-run`. If it moves anything, run
   `uv lock --upgrade` as a commit of its own, then all checks.
2. Set `version` in the four packages' `pyproject.toml`, the pins
   `benethos-mailbox-client==X.Y.Z` and `benethos-mailbox-common==X.Y.Z`
   in the MCP server's and `benethos-mailbox-common==X.Y.Z` in the
   service's, then `uv lock` and `uv sync`. `test_packaging.py` names every version example in the
   documentation that still shows the old one.
3. Close `[Unreleased]` in `CHANGELOG.md` as `[X.Y.Z] - <date>`.
4. Freeze the migrations new in this release: add `fingerprint(N)` of
   each to `RELEASED` in `tests/data/storage/test_sqlite.py`.
5. After the squash merge: an annotated tag `vX.Y.Z` on `main`, pushed,
   then `gh release create vX.Y.Z --verify-tag` with the changelog section
   as the notes. The published release starts `publish.yml`, which
   uploads the four packages to PyPI and both images to GHCR.
6. Check what shipped: the four packages on PyPI, and each image's tags
   `X.Y.Z`, `X.Y` and `latest` on the same revision.
