"""A database file at an older schema, made by the migrations up to it,
for the tests of the steps after it. And SQL as text on a ``Database``,
for a test that looks below its repositories: the one place a test hands
it SQL, also inside ``with db.transaction():``."""

from __future__ import annotations

import sqlite3
from collections.abc import Iterable, Sequence
from pathlib import Path
from typing import Any

from benethos_mailbox_service.data.storage import Database
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


def select(db: Database, sql: str, params: Sequence[Any] = ()) -> list[Any]:
    """The rows ``sql`` reads from ``db``, each by name and by place."""
    return db.query(sql, tuple(params))


def value(db: Database, sql: str, params: Sequence[Any] = ()) -> Any:
    """The first value of the first row ``sql`` reads, or None."""
    row = db.one(sql, tuple(params))
    return None if row is None else row[0]


def run(db: Database, sql: str, params: Sequence[Any] = ()) -> int:
    """``sql`` on ``db``, in the transaction open or in one of its own.
    The rows it changed."""
    return db.execute(sql, tuple(params))


def run_many(db: Database, sql: str, rows: Iterable[Sequence[Any]]) -> None:
    """``sql`` once for each of ``rows``, in one transaction."""
    with db.transaction() as conn:
        conn.executemany(sql, rows)
