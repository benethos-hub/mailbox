# Working guidelines for the service

The rules that hold for `mailbox-service` alone. The rules for the
whole repository, the golden rules among them, are in the
[CLAUDE.md of the root](../../CLAUDE.md): read it first.

## The contract

`docs/mailbox-service/openapi.json` is the contract (golden rule 4). It
is checked in and a test compares it with the code. After any change to
a route or model, regenerate it with
`uv run benethos-mailbox-service openapi > docs/mailbox-service/openapi.json`
and review the diff like code. `operationId` is the route function name
and must stay stable, since generated clients and the MCP server depend
on it. The client's requests are held to it as well
([its CLAUDE.md](../mailbox-client/CLAUDE.md)).

## Conventions

- Every error response uses the envelope `{"error": {"code", "message"}}`.
- Lists are paged with an opaque `next_cursor`, never with page numbers.
- A change to the database schema is a new revision: a class
  `RNNNN<Subject>` of the base `Revision` (`revisions/revision.py`) in a
  module `rNNNN_<subject>.py` in
  `src/benethos_mailbox_service/data/storage/sql/revisions/versions/`,
  with the next number as `version`. It makes its step in `steps`: the
  tables through `alembic.op`, the rows through `self.conn`, rows worked
  out in Python with `self.rewrite`. `check`, `refuse`, `note`,
  `keeps_copy` and `in_transaction` are there when a step needs them.
  The base writes `meta.schema_version` after the step. The module ends
  with `revision, down_revision, upgrade = RNNNN<Subject>.alembic()`, and
  `SCHEMA_VERSION` in `revisions/__init__.py` becomes its number. The
  definitions in `data/storage/sql/schema.py` change with it, and a test
  holds the two alike. The module's docstring says what it does and why.
  It runs on SQLite and on PostgreSQL, and only forward. A change to the
  base that would change what a released revision does is a new
  revision, never an edit of the base. A revision that builds a table anew which others refer
  to needs care on SQLite, and a test with rows in the tables that refer
  to it: with foreign keys on, SQLite can delete the rows of a table it
  drops, and that reaches the tables that refer to it. Measure it with
  the first such revision.
- The old steps up to schema 26, classes in
  `src/benethos_mailbox_service/data/storage/sqlite/migrations/`, are
  closed: no step is added there.
- A step that shipped in a release is never changed. `RELEASED` in
  `tests/data/storage/test_sqlite.py` holds the fingerprint of each old
  step, `RELEASED_REVISIONS` in `tests/data/storage/test_sql_revisions.py`
  the one of each revision.

## The configuration UI

How the pages look and behave, and the checklist for a new page:
[docs/mailbox-service/UI.md](../../docs/mailbox-service/UI.md).

The UI in real browsers is the one check that runs its JavaScript:
`uv run --group browser playwright install chromium firefox webkit`
once, then `MAILBOX_BROWSER_TESTS=1 uv run --group browser pytest
packages/mailbox-service/tests/browser -n 0`. The sign-in with a code must
go on by itself through htmx, and no page reached from the overview
may break the content security policy or miss a file of its own. In
Chromium a passkey is made on the page Second factor and signs in,
through its virtual authenticator. The default run leaves the folder
out, CI's browser job runs it. Run it after a change to a template, to
`static/` or to htmx.
