"""A restore on PostgreSQL: into an empty schema only, table for table
the export, refused while a service holds the schema or where it holds
tables, and leaving nothing of itself when the backup does not hold, or
a database the service does not open when it dies half way."""

from __future__ import annotations

import io
from dataclasses import replace
from pathlib import Path
from typing import Any

import pytest

from benethos_mailbox_service.data.backup import (
    BackupError,
    Manifest,
    create_backup,
    restore_on_server,
    write_backup,
)
from benethos_mailbox_service.data.export import write_export
from benethos_mailbox_service.data.secrets import cipher
from benethos_mailbox_service.data.storage import Database, ServerPlace
from benethos_mailbox_service.errors import StorageError, StorageUnavailableError

from ..postgres_helpers import connect, role, schemas

MASTER = cipher.new_key()


def _exported(db: Database) -> bytes:
    out = io.BytesIO()
    write_export(db, out)
    return out.getvalue()


@pytest.fixture
def backup(source: Database, tmp_path: Path) -> Path:
    target = tmp_path / "b.bak"
    create_backup(source, MASTER, target, "9.9.9", format=3)
    return target


def test_a_restore_into_an_empty_schema_is_the_export(
    source: Database, backup: Path
) -> None:
    with role() as server:
        manifest = restore_on_server(backup, MASTER, server)
        restored = Database(place=ServerPlace(server))
        try:
            assert _exported(restored) == _exported(source)
        finally:
            restored.close()
    assert manifest.format == 3
    source.close()


def test_a_schema_with_tables_is_refused_and_kept(
    source: Database, backup: Path
) -> None:
    with role() as server:
        Database(place=ServerPlace(server)).close()
        held = Database(place=ServerPlace(server))
        before = _exported(held)
        held.close()
        with pytest.raises(BackupError, match="empty schema only"):
            restore_on_server(backup, MASTER, server)
        after = Database(place=ServerPlace(server))
        try:
            assert _exported(after) == before
        finally:
            after.close()
    source.close()


def test_a_backup_that_does_not_hold_leaves_no_table(
    source: Database, tmp_path: Path
) -> None:
    export = tmp_path / "export"
    export.write_bytes(_exported(source))
    with source.view() as records:
        schema = records.schema_version()
    import hashlib

    rows = {t.name: len(list(source.rows(t.name))) for t in source.tables()}
    wrong = Manifest(
        "9.9.9",
        schema,
        "2026-11-26T00:00:00Z",
        hashlib.sha256(export.read_bytes()).hexdigest(),
        rows=rows | {"users": rows["users"] + 1},
        format=3,
    )
    write_backup(export, wrong, MASTER, tmp_path / "wrong.bak")
    with role() as server:
        with pytest.raises(BackupError, match="does not match its manifest"):
            restore_on_server(tmp_path / "wrong.bak", MASTER, server)
        place = ServerPlace(server)
        place.open(26, 26)
        try:
            assert place.tables() == []
        finally:
            place.close()
        assert server.schema_name in schemas()
    source.close()


def test_a_restore_while_a_service_runs_is_refused(
    source: Database, backup: Path
) -> None:
    with role() as server:
        running = Database(place=ServerPlace(server))
        try:
            with running.serving():
                with pytest.raises(BackupError, match="the service is running"):
                    restore_on_server(backup, MASTER, replace(server))
        finally:
            running.close()
    source.close()


def test_a_restore_that_dies_half_way_is_not_opened(
    source: Database, backup: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    fill = Database.fill
    filled: list[str] = []

    def dying(self: Database, table: str, *args: Any) -> int:
        if len(filled) == 4:
            raise SystemExit("killed")
        filled.append(table)
        return fill(self, table, *args)

    monkeypatch.setattr(Database, "fill", dying)
    # A process that is killed cleans nothing up.
    monkeypatch.setattr(ServerPlace, "drop_tables", lambda self: None)
    with role() as server:
        with pytest.raises(SystemExit):
            restore_on_server(backup, MASTER, server)
        monkeypatch.setattr(Database, "fill", fill)
        with pytest.raises(StorageError, match="a move or restore into this database"):
            Database(place=ServerPlace(server))
    source.close()


def test_a_failed_restore_names_its_cause(source: Database, backup: Path) -> None:
    from psycopg import sql

    with role() as server, connect() as admin:
        admin.execute(
            sql.SQL("REVOKE CREATE ON SCHEMA {0} FROM {0}").format(
                sql.Identifier(server.role)
            )
        )
        with pytest.raises(StorageError, match="InsufficientPrivilege"):
            restore_on_server(backup, MASTER, server)
    source.close()


def test_a_server_away_at_the_lock_is_no_running_service(
    source: Database, backup: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    def away(place: ServerPlace) -> None:
        raise StorageUnavailableError(1, "AdminShutdown (57P01)")

    monkeypatch.setattr(ServerPlace, "claimed", away)
    with role() as server:
        with pytest.raises(StorageUnavailableError):
            restore_on_server(backup, MASTER, server)
    source.close()
