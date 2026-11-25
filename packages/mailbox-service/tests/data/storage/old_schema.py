"""A database file at an older schema, made by the migrations up to it,
for the tests of the steps after it."""

from __future__ import annotations

import sqlite3
from pathlib import Path

from benethos_mailbox_service.data.storage.sqlite.migrations import MIGRATIONS


def at_schema(path: Path, version: int) -> sqlite3.Connection:
    """A connection to a new database at ``path``, migrated to ``version``
    and no further. The caller fills and closes it."""
    raw = sqlite3.connect(path, isolation_level=None)
    raw.row_factory = sqlite3.Row
    raw.execute("PRAGMA foreign_keys = ON")
    MIGRATIONS.prepare(raw)
    for number in range(1, version + 1):
        raw.execute("BEGIN")
        MIGRATIONS.apply(raw, MIGRATIONS.step(number))
        raw.execute("COMMIT")
    return raw
