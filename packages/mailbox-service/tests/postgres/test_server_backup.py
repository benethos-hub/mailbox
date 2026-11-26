"""Backups of a database on PostgreSQL: format 3 by default, read from a
view of one moment while a writer writes, and checked."""

from __future__ import annotations

import threading
from collections.abc import Iterator
from pathlib import Path

import pytest
from pydantic import SecretStr

from benethos_mailbox_service.assembly import build_services
from benethos_mailbox_service.cli import main
from benethos_mailbox_service.config import Settings
from benethos_mailbox_service.data.backup import MAGIC_3, create_backup, verify_backup
from benethos_mailbox_service.data.models import ProviderType, User
from benethos_mailbox_service.data.storage import Server, repositories_on

from ..conftest import create_account
from ..postgres_helpers import admin, database, role, schema


@pytest.fixture
def on_server(tmp_path: Path, monkeypatch: pytest.MonkeyPatch) -> Iterator[Server]:
    """Settings of a service on a schema of its own role, a key in the
    environment, and one account with a password."""
    with role() as server:
        password = tmp_path / "database_password"
        password.write_text(server.password, encoding="utf-8")
        who = admin()
        monkeypatch.setenv("MAILBOX_SERVICE_DATA_DIR", str(tmp_path / "data"))
        monkeypatch.setenv("MAILBOX_SERVICE_STORAGE", "postgres")
        monkeypatch.setenv(
            "MAILBOX_SERVICE_DATABASE_URL",
            f"postgresql://{server.role}@{who.host}:{who.port}/{who.database}",
        )
        monkeypatch.setenv("MAILBOX_SERVICE_DATABASE_PASSWORD_FILE", str(password))
        monkeypatch.setenv("MAILBOX_SERVICE_KEY_PROVIDER", "file")
        monkeypatch.setenv(
            "MAILBOX_SERVICE_KEY_FILE", str(tmp_path / "secret" / "master.key")
        )
        services = build_services(Settings())
        try:
            services.vault.initialize()
            create_account(
                services.accounts,
                ProviderType.MEMORY,
                "owner@example.com",
                credentials={"password": SecretStr("hunter2")},
            )
        finally:
            services.close()
        yield server


def test_a_backup_on_a_server_is_format_3(
    on_server: Server, tmp_path: Path, capsys: pytest.CaptureFixture[str]
) -> None:
    target = tmp_path / "out" / "mailbox.bak"
    assert main(["backup", str(target)]) == 0
    assert "Backup written in format 3:" in capsys.readouterr().err
    assert target.read_bytes().startswith(MAGIC_3)
    assert main(["backup", "verify", str(target)]) == 0
    assert ", format 3, " in capsys.readouterr().err


def test_a_backup_while_a_writer_writes(tmp_path: Path) -> None:
    """The rows of the manifest are those of the export, of one moment."""
    with schema() as name:
        db = database(name)
        users = repositories_on(db).users
        stop = threading.Event()
        written: list[int] = []

        def write() -> None:
            n = 0
            while not stop.is_set():
                users.save(User(id=f"usr_{n}", name=f"user {n}"))
                written.append(n)
                n += 1

        writer = threading.Thread(target=write)
        writer.start()
        try:
            while len(written) < 20:
                stop.wait(0.01)
            manifest = create_backup(
                db, b"k" * 32, tmp_path / "b.bak", "9.9.9", format=3
            )
        finally:
            stop.set()
            writer.join()
            db.close()
    assert manifest.rows is not None
    assert 0 < manifest.rows["users"] <= len(written)
    checked = verify_backup(tmp_path / "b.bak", b"k" * 32, tmp_path / "scratch.db")
    assert checked.rows == manifest.rows
