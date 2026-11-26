"""A database file at an older schema, made by the migrations up to it,
for the tests of the steps after it, the seed of schema 25 in one, and
the export of a database as bytes. And SQL as text on a ``Database``,
for a test that looks below its repositories: the one place a test hands
it SQL, on the connection of the driver beneath it, also inside
``with db.transaction():``."""

from __future__ import annotations

import io
import sqlite3
from collections.abc import Iterable, Sequence
from pathlib import Path
from typing import Any

from benethos_mailbox_service.data.export import write_export
from benethos_mailbox_service.data.storage import Database, Records
from benethos_mailbox_service.data.storage.sqlite.file import translated
from benethos_mailbox_service.data.storage.sqlite.migrations import MIGRATIONS

# Every table filled at schema 25, with two values an older version
# wrote that do not fit their columns: a text for a number, texts for
# bytes.
SEED = Path(__file__).parent / "data" / "storage" / "seeds" / "schema_25.sql"


def seed_25(path: Path, *, fitting: bool = False) -> Database:
    """The seed of schema 25 at ``path``, migrated. ``fitting``: without
    the values that do not fit their columns, as a move needs it."""
    raw = at_schema(path, 25)
    raw.executescript(SEED.read_text(encoding="utf-8"))
    if fitting:
        raw.execute(
            "UPDATE webhook_attempts SET events = CAST(substr(events, 2, 1) AS INTEGER)"
        )
        raw.execute(
            "UPDATE passkeys SET credential_id = CAST(credential_id AS BLOB),"
            " credential = CAST(credential AS BLOB)"
        )
    raw.close()
    return Database(path)


def exported(records: Records) -> bytes:
    """The export of ``records``, as bytes."""
    out = io.BytesIO()
    write_export(records, out)
    return out.getvalue()


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
    with translated():
        rows: list[Any] = _driver(db).execute(sql, tuple(params)).fetchall()
        return rows


def value(db: Database, sql: str, params: Sequence[Any] = ()) -> Any:
    """The first value of the first row ``sql`` reads, or None."""
    with translated():
        row = _driver(db).execute(sql, tuple(params)).fetchone()
    return None if row is None else row[0]


def run(db: Database, sql: str, params: Sequence[Any] = ()) -> int:
    """``sql`` on ``db``, in the transaction open or in one of its own.
    The rows it changed."""
    with translated():
        changed: int = _driver(db).execute(sql, tuple(params)).rowcount
        return changed


def run_many(db: Database, sql: str, rows: Iterable[Sequence[Any]]) -> None:
    """``sql`` once for each of ``rows``, in one transaction."""
    with db.transaction(), translated():
        _driver(db).executemany(sql, rows)


def _driver(db: Database) -> sqlite3.Connection:
    """The connection of the driver beneath ``db``: the one place a test
    knows where it sits."""
    driver: sqlite3.Connection = db._place.driver
    return driver


def shape(conn: sqlite3.Connection) -> dict[str, Any]:
    """The form of the tables of a SQLite database, without its rows:
    per table its columns (name, type, NOT NULL, default, place in the
    key), its references with ON DELETE, its indexes and whether it
    counts with AUTOINCREMENT. An index SQLite made for a key or a
    UNIQUE is named by where it comes from and its columns, never by
    its name, whose number follows the order in CREATE TABLE."""
    found: dict[str, Any] = {}
    tables = conn.execute(
        "SELECT name, sql FROM sqlite_master WHERE type = 'table'"
        " AND name NOT LIKE 'sqlite_%'"
    ).fetchall()
    for name, sql in tables:
        columns = [
            (r[1], r[2], r[3], r[4], r[5])
            for r in conn.execute("SELECT * FROM pragma_table_info(?)", (name,))
        ]
        refers = sorted(
            (r[3], r[2], r[4], r[6])
            for r in conn.execute("SELECT * FROM pragma_foreign_key_list(?)", (name,))
        )
        indexes = set()
        for r in conn.execute("SELECT * FROM pragma_index_list(?)", (name,)):
            index, unique, origin, partial = r[1], r[2], r[3], r[4]
            cols = tuple(
                c[2]
                for c in conn.execute(
                    "SELECT * FROM pragma_index_info(?) ORDER BY seqno", (index,)
                )
            )
            named = index if origin == "c" else origin
            indexes.add((named, unique, cols, partial))
        found[name] = {
            "columns": columns,
            "refers": refers,
            "indexes": sorted(indexes),
            "counted": "AUTOINCREMENT" in sql.upper(),
        }
    return found
