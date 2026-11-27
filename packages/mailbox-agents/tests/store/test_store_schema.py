"""The schema of the state file three ways alike: as the baseline revision
makes a new file, as the old steps bring an old file to it, and as
``store/schema.py`` defines it. And a file of each old schema keeps its
rows on the way."""

from __future__ import annotations

import inspect
import sqlite3
from contextlib import closing
from datetime import UTC, datetime
from pathlib import Path
from typing import Any

import pytest
import sqlalchemy as sa

from benethos_mailbox_agents.records import MessageRef
from benethos_mailbox_agents.store import MIGRATIONS, SCHEMA_VERSION, Store
from benethos_mailbox_agents.store.schema import METADATA

NOW = datetime(2026, 11, 27, 9, 0, tzinfo=UTC)
REF = MessageRef(account_id="acc", message_id="m1")


def _shape(path: Path) -> dict[str, Any]:
    """Per table its columns (name, type, NOT NULL, default, place in the
    key) and its indexes with their columns, the bookkeeping of the
    revisions left out."""
    with closing(sqlite3.connect(path)) as db:
        tables = [
            row[0]
            for row in db.execute(
                "SELECT name FROM sqlite_master WHERE type = 'table' "
                "AND name NOT LIKE 'sqlite_%' AND name != 'alembic_version'"
            )
        ]
        return {
            name: (
                [tuple(r[1:]) for r in db.execute(f"PRAGMA table_info({name})")],
                sorted(
                    (
                        index[1],
                        [c[2] for c in db.execute(f"PRAGMA index_info({index[1]})")],
                    )
                    for index in db.execute(f"PRAGMA index_list({name})")
                    if not index[1].startswith("sqlite_autoindex")
                ),
            )
            for name in sorted(tables)
        }


def _old_steps(path: Path, upto: int) -> None:
    with closing(sqlite3.connect(path)) as raw, raw:
        for number in range(1, upto + 1):
            for statement in MIGRATIONS.step(number).statements:
                raw.execute(inspect.cleandoc(statement))
        raw.execute(f"PRAGMA user_version = {upto}")


def test_the_baseline_the_old_steps_and_the_definitions_agree(tmp_path: Path) -> None:
    Store.open(tmp_path / "new.db").close()
    _old_steps(tmp_path / "old.db", MIGRATIONS.schema_version)
    engine = sa.create_engine(f"sqlite:///{(tmp_path / 'defined.db').as_posix()}")
    METADATA.create_all(engine)
    engine.dispose()

    made = _shape(tmp_path / "new.db")

    assert made == _shape(tmp_path / "old.db")
    assert made == _shape(tmp_path / "defined.db")
    assert MIGRATIONS.schema_version == SCHEMA_VERSION


@pytest.mark.parametrize("schema", [1, 2, 3, 4])
def test_a_file_of_an_old_schema_keeps_its_rows(tmp_path: Path, schema: int) -> None:
    path = tmp_path / "counting.db"
    _old_steps(path, schema)
    at = NOW.isoformat()
    with closing(sqlite3.connect(path)) as raw, raw:
        raw.execute(
            "INSERT INTO messages (account_id, message_id, state, attempts, "
            "next_attempt, created, updated) VALUES ('acc', 'm1', 'done', 2, ?, ?, ?)",
            (at, at, at),
        )
        raw.execute(
            "INSERT INTO cursor (id, state, updated) VALUES (1, 'token-7', ?)", (at,)
        )

    with Store.open(path) as store:
        assert store.version == SCHEMA_VERSION
        assert store.migrated is not None
        assert (store.migrated.before, store.migrated.after) == (schema, SCHEMA_VERSION)
        row = store.message(REF)
        assert row is not None
        assert (row.state, row.attempts) == ("done", 2)
        assert store.cursor() == "token-7"

    [kept] = tmp_path.glob("counting.db.before-schema-5-*")
    with closing(sqlite3.connect(kept)) as copy:
        assert copy.execute("PRAGMA user_version").fetchone()[0] == schema
    with Store.open(path, read_only=True) as reader:
        assert reader.counts()["done"] == 1
