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
- A change to the database schema is a new migration: a class
  `VNNNN<Subject>` of the base `Migration` in a module
  `vNNNN_<subject>.py` in
  `src/benethos_mailbox_service/data/storage/sqlite/migrations/versions/`
  with the next number, added to the registry `MIGRATIONS` in the
  `__init__.py` of `migrations/`. The module's docstring says what it
  does and why. Each statement stands alone, and a step in Python is the
  method `before`. A migration that shipped in a release is never changed:
  `RELEASED` in `tests/data/storage/test_sqlite.py` holds the fingerprint
  of each.

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
