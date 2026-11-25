"""A database of every released schema, every table filled, migrated to
this version: every row is still there and reads as it did.

Each seed in ``seeds/`` is SQL for one schema, written once and never
changed, like a migration. A release with a new schema adds its own.
"""

from __future__ import annotations

import sqlite3
from pathlib import Path
from typing import Any

import pytest

from benethos_mailbox_service.data.models import SendFilter
from benethos_mailbox_service.data.storage import (
    Database,
    repositories_on,
)

from ...schema_helpers import at_schema

SEEDS = Path(__file__).parent / "seeds"

# The schema of each seed, and the release it came with.
SEEDED = {
    13: "0.2.0",
    17: "0.3.0",
    19: "0.4.0",
    22: "0.5.0",
    24: "0.8.0 to 0.11.1",
    25: "the outbox",
}

# What a migration removes from a seed on purpose: by schema of the seed,
# the table and the keys of its rows, with the migration that removes them.
# None so far.
REMOVED: dict[int, dict[str, set[tuple[Any, ...]]]] = {}

# Rows every migration changes on purpose: the version of the schema.
CHANGED = {("meta", ("schema_version",))}

Rows = dict[str, dict[tuple[Any, ...], dict[str, Any]]]


def _seeded(path: Path, schema: int) -> tuple[Rows, dict[str, list[str]]]:
    """The seed of ``schema`` in a new database at ``path``: its rows by
    table and key, and the key columns of each table."""
    raw = at_schema(path, schema)
    raw.executescript((SEEDS / f"schema_{schema}.sql").read_text(encoding="utf-8"))
    keys = {
        table: [
            r["name"]
            for r in sorted(
                raw.execute(f"PRAGMA table_info({table})"), key=lambda r: r["pk"]
            )
            if r["pk"]
        ]
        for table in _tables(raw)
    }
    rows = {table: _rows(raw, table, keys[table]) for table in keys}
    raw.close()
    return rows, keys


def _tables(conn: sqlite3.Connection) -> list[str]:
    return [
        r[0]
        for r in conn.execute(
            "SELECT name FROM sqlite_master WHERE type = 'table'"
            " AND name NOT LIKE 'sqlite_%' ORDER BY name"
        )
    ]


def _rows(
    conn: sqlite3.Connection, table: str, key: list[str]
) -> dict[tuple[Any, ...], dict[str, Any]]:
    conn.row_factory = sqlite3.Row
    return {
        tuple(row[c] for c in key): dict(row)
        for row in conn.execute(f"SELECT * FROM {table}")
    }


def test_there_is_a_seed_of_each_schema() -> None:
    assert sorted(p.name for p in SEEDS.iterdir()) == [
        f"schema_{n}.sql" for n in sorted(SEEDED)
    ]


@pytest.mark.parametrize("schema", sorted(SEEDED))
def test_every_seeded_row_survives_the_migrations(tmp_path: Path, schema: int) -> None:
    path = tmp_path / "old.db"
    before, keys = _seeded(path, schema)
    assert all(len(rows) >= 2 for rows in before.values()), "a table left empty"
    db = Database(path)
    conn = sqlite3.connect(path)
    try:
        removed = REMOVED.get(schema, {})
        for table, rows in before.items():
            after = _rows(conn, table, keys[table])
            for key, row in rows.items():
                if key in removed.get(table, set()):
                    assert key not in after, (table, key)
                    continue
                assert key in after, (table, key)
                if (table, key) in CHANGED:
                    continue
                kept = {c: after[key][c] for c in row}
                assert kept == row, (table, key)
        assert conn.execute("PRAGMA integrity_check").fetchone()[0] == "ok"
        assert conn.execute("PRAGMA foreign_key_check").fetchall() == []
    finally:
        conn.close()
        db.close()


@pytest.mark.parametrize("schema", sorted(SEEDED))
def test_a_migrated_seed_reads_as_it_was_written(tmp_path: Path, schema: int) -> None:
    path = tmp_path / "old.db"
    _seeded(path, schema)
    db = Database(path)
    feed = repositories_on(db).changes
    assert [e.seq for e in feed.after(["acc_seed1", "acc_seed2"], 0, limit=10)] == [
        5,
        7,
    ]
    assert feed.last() == 9
    index = repositories_on(db).index
    entries = index.in_folders("acc_seed2", ["f_inbox"])
    assert [e.id for e in entries] == ["msg_seed_c", "msg_seed_d", "msg_seed_b"]
    key = repositories_on(db).keys.active()
    assert key is not None
    assert key.key_id == "key_seed_a"
    found = repositories_on(db).sends.list(
        "acc_seed2", limit=10, before=None, matching=SendFilter(recipient="JÖRG.REC")
    )
    assert [r.id for r in found] == ["snd_seed1"]
    db.close()
