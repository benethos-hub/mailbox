"""The move of the records: the check before anything is written names
every column whose values do not fit its kind, with how many, and never
a value."""

from __future__ import annotations

import sqlite3
from pathlib import Path
from typing import Any

import pytest

from benethos_mailbox_common.paths import locks
from benethos_mailbox_service.data.move import (
    Misfit,
    MoveError,
    check_move,
    misfits,
    move_records,
    refused,
)
from benethos_mailbox_service.data.storage import Database, service_lock
from benethos_mailbox_service.errors import StorageError

from ..schema_helpers import at_schema, exported, seed_25


@pytest.fixture
def seeded(tmp_path: Path) -> Database:
    """The seed of schema 25, migrated: it holds a text in a column of
    numbers and texts in two columns of bytes, as an older version wrote
    them."""
    return seed_25(tmp_path / "seeded.db")


def test_every_column_whose_values_do_not_fit_is_named(seeded: Database) -> None:
    with seeded.view() as records:
        found = misfits(records)
    seeded.close()
    assert found == [
        Misfit("passkeys", "credential_id", 2),
        Misfit("passkeys", "credential", 2),
        Misfit("webhook_attempts", "events", 2),
    ]


def test_the_message_names_columns_and_counts_never_a_value(
    seeded: Database,
) -> None:
    with seeded.view() as records:
        values = {
            str(v)
            for table in ("passkeys", "webhook_attempts")
            for row in records.rows(table)
            for v in row
            if isinstance(v, str)
        }
        message = str(refused(misfits(records)))
    seeded.close()
    assert "webhook_attempts.events: 2" in message
    assert "passkeys.credential: 2" in message
    assert not [v for v in values if len(v) > 3 and v in message]


def test_a_database_this_version_wrote_fits(tmp_path: Path) -> None:
    db = Database(tmp_path / "new.db")
    with db.view() as records:
        assert misfits(records) == []
    db.close()


def _exported(path: Path) -> bytes:
    db = Database(path)
    try:
        return exported(db)
    finally:
        db.close()


def test_a_move_copies_every_record_and_leaves_no_mark(tmp_path: Path) -> None:
    seed_25(tmp_path / "from.db", fitting=True).close()
    before = _exported(tmp_path / "from.db")
    moved = move_records(tmp_path / "from.db", tmp_path / "to.db")
    assert _exported(tmp_path / "to.db") == before
    assert _exported(tmp_path / "from.db") == before
    assert moved.tables > 20
    assert moved.rows > 0


def test_a_check_writes_nothing(tmp_path: Path) -> None:
    seed_25(tmp_path / "from.db", fitting=True).close()
    before = (tmp_path / "from.db").read_bytes()
    files = {p.name for p in tmp_path.iterdir()}
    found = check_move(tmp_path / "from.db")
    assert found.rows > 0
    assert (tmp_path / "from.db").read_bytes() == before
    # The lock of a snapshot stays, as after a backup.
    assert {p.name for p in tmp_path.iterdir() if p.suffix != ".lock"} <= files


def test_values_that_do_not_fit_stop_the_move_before_the_target(
    seeded: Database, tmp_path: Path
) -> None:
    seeded.close()
    with pytest.raises(MoveError, match="webhook_attempts.events: 2"):
        move_records(tmp_path / "seeded.db", tmp_path / "to.db")
    assert not (tmp_path / "to.db").exists()


def test_a_target_that_exists_is_refused(tmp_path: Path) -> None:
    seed_25(tmp_path / "from.db", fitting=True).close()
    Database(tmp_path / "to.db").close()
    with pytest.raises(MoveError, match="a new database only"):
        move_records(tmp_path / "from.db", tmp_path / "to.db")


def test_a_running_service_on_either_side_refuses_the_move(tmp_path: Path) -> None:
    seed_25(tmp_path / "from.db", fitting=True).close()
    running = Database(tmp_path / "from.db")
    with running.serving() as free:
        assert free
        with pytest.raises(MoveError, match="the service is running"):
            move_records(tmp_path / "from.db", tmp_path / "to.db")
        with pytest.raises(MoveError, match="the service is running"):
            check_move(tmp_path / "from.db")
    running.close()
    with locks.exclusive_lock(service_lock(tmp_path / "to.db")):
        with pytest.raises(MoveError, match="the service is running"):
            move_records(tmp_path / "from.db", tmp_path / "to.db")


def test_a_move_that_fails_halfway_leaves_a_target_the_service_refuses(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    seed_25(tmp_path / "from.db", fitting=True).close()
    fill = Database.fill

    def failing(self: Database, table: str, *args: Any) -> int:
        if table == "users":
            raise StorageError("the disk is full")
        return fill(self, table, *args)

    monkeypatch.setattr(Database, "fill", failing)
    with pytest.raises(StorageError, match="the disk is full"):
        move_records(tmp_path / "from.db", tmp_path / "to.db")
    monkeypatch.undo()
    with pytest.raises(StorageError, match="a move or restore into this database"):
        Database(tmp_path / "to.db")
    Database(tmp_path / "from.db").close()


def test_a_source_of_an_older_schema_is_refused_unchanged(tmp_path: Path) -> None:
    raw = at_schema(tmp_path / "old.db", 25)
    raw.close()
    before = (tmp_path / "old.db").read_bytes()
    with pytest.raises(MoveError, match="start the service on it once"):
        move_records(tmp_path / "old.db", tmp_path / "to.db")
    assert (tmp_path / "old.db").read_bytes() == before


def test_a_text_with_nul_does_not_fit(tmp_path: Path) -> None:
    path = tmp_path / "nul.db"
    seed_25(path, fitting=True).close()
    raw = sqlite3.connect(path)
    raw.execute(
        "UPDATE users SET name = 'a' || char(0) || 'secret-name'"
        " WHERE rowid = (SELECT min(rowid) FROM users)"
    )
    raw.commit()
    raw.close()
    db = Database(path)
    with db.view() as records:
        found = misfits(records)
    db.close()
    assert found == [Misfit("users", "name", 1)]
    assert "secret-name" not in str(refused(found))


def test_the_mark_of_a_move_is_no_record(tmp_path: Path) -> None:
    db = Database(tmp_path / "marked.db")
    db.mark_move("2026-11-26T00:00:00Z")
    keys = {row[0] for row in db.rows("meta")}
    with db.view() as records:
        seen = {row[0] for row in records.rows("meta")}
    db.close()
    assert "schema_version" in keys
    assert "move_started" not in keys | seen
