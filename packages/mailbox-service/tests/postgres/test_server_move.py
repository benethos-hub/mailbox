"""The move on PostgreSQL: a database in SQLite into a schema and back is
the same export, the counting keys count on, a schema with tables or a
running service refuses it, and a move that fails leaves a schema the
service does not open."""

from __future__ import annotations

import io
from datetime import UTC, datetime
from pathlib import Path
from typing import Any

import pytest

from benethos_mailbox_service.data.export import write_export
from benethos_mailbox_service.data.models import ChangeRecord
from benethos_mailbox_service.data.move import MoveError, move_records
from benethos_mailbox_service.data.storage import Database, repositories_on
from benethos_mailbox_service.errors import StorageError

from ..postgres_helpers import database, schema, server


def _exported(db: Database) -> bytes:
    out = io.BytesIO()
    write_export(db, out)
    return out.getvalue()


def test_a_move_there_and_back_is_the_same_export(
    source: Database, tmp_path: Path
) -> None:
    before = _exported(source)
    source.close()
    with schema() as name:
        there = move_records(tmp_path / "source.db", server(name))
        on_server = database(name)
        try:
            assert _exported(on_server) == before
        finally:
            on_server.close()
        back = move_records(server(name), tmp_path / "back.db")
    assert there == back
    returned = Database(tmp_path / "back.db")
    try:
        assert _exported(returned) == before
    finally:
        returned.close()


def test_the_numbers_stay_and_the_next_change_counts_on(
    source: Database, tmp_path: Path
) -> None:
    held = [row[0] for row in source.rows("changes")]
    source.close()
    record = ChangeRecord(
        type="message.created",
        id="msg_1",
        account_id="acc_seed2",
        at=datetime(2026, 11, 26, tzinfo=UTC),
    )
    with schema() as name:
        move_records(tmp_path / "source.db", server(name))
        moved = database(name)
        try:
            repositories_on(moved).changes.append([record])
            numbers = [row[0] for row in moved.rows("changes")]
        finally:
            moved.close()
    assert numbers[:-1] == held
    assert numbers[-1] > max(held)


def test_a_schema_with_tables_is_refused_and_kept(
    source: Database, tmp_path: Path
) -> None:
    source.close()
    with schema() as name:
        database(name).close()
        with pytest.raises(MoveError, match="holds tables"):
            move_records(tmp_path / "source.db", server(name))
        kept = database(name)
        try:
            assert list(kept.rows("users")) == []
        finally:
            kept.close()


def test_a_service_on_the_schema_refuses_the_move(
    source: Database, tmp_path: Path
) -> None:
    source.close()
    with schema() as name:
        move_records(tmp_path / "source.db", server(name))
        running = database(name)
        try:
            with running.serving():
                with pytest.raises(MoveError, match="the service is running"):
                    move_records(server(name), tmp_path / "back.db")
        finally:
            running.close()
    assert not (tmp_path / "back.db").exists()


def test_a_move_that_fails_halfway_leaves_a_schema_the_service_refuses(
    source: Database, tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    source.close()
    fill = Database.fill

    def failing(self: Database, table: str, *args: Any) -> int:
        if table == "users":
            raise StorageError("the server went away")
        return fill(self, table, *args)

    with schema() as name:
        monkeypatch.setattr(Database, "fill", failing)
        with pytest.raises(StorageError, match="the server went away"):
            move_records(tmp_path / "source.db", server(name))
        monkeypatch.undo()
        with pytest.raises(StorageError, match="a storage move into this database"):
            database(name)
