"""A backup checked on an installation whose database is on a server:
nothing of it is decrypted onto a disk, in any format, and a changed
backup is found as before."""

from __future__ import annotations

import json
from dataclasses import asdict
from pathlib import Path

import pytest
from pydantic import SecretStr

from benethos_mailbox_service.assembly import build_services
from benethos_mailbox_service.cli import main
from benethos_mailbox_service.config import Settings
from benethos_mailbox_service.data.backup import MAGIC_1, Manifest
from benethos_mailbox_service.data.backup import backups as backup_module
from benethos_mailbox_service.data.models import ProviderType
from benethos_mailbox_service.data.secrets import cipher
from benethos_mailbox_service.data.storage import inspect_file

from ..conftest import create_account


def _files(*folders: Path) -> list[Path]:
    return sorted(p for folder in folders for p in folder.rglob("*"))


def _version_1(database: Path, master: bytes, target: Path) -> None:
    """A backup of format 1, as the first releases wrote it."""
    import hashlib

    data = database.read_bytes()
    manifest = Manifest(
        "0.2.0",
        inspect_file(database),
        "2026-01-01T00:00:00Z",
        hashlib.sha256(data).hexdigest(),
    )
    header = MAGIC_1 + json.dumps(asdict(manifest)).encode() + b"\n"
    key = cipher.derive(master, b"mailbox-service backup v1")
    found = cipher.encrypt(key, data, header)
    target.write_bytes(header + found.nonce + found.ciphertext)


@pytest.fixture
def backups(tmp_path: Path, monkeypatch: pytest.MonkeyPatch) -> dict[int, Path]:
    """A backup of each format, written on SQLite. Then the settings name
    a database on a server, which a check never reaches."""
    monkeypatch.setenv("MAILBOX_SERVICE_DATA_DIR", str(tmp_path / "data"))
    monkeypatch.setenv("MAILBOX_SERVICE_STORAGE", "sqlite")
    monkeypatch.setenv("MAILBOX_SERVICE_KEY_PROVIDER", "file")
    key_file = tmp_path / "secret" / "master.key"
    monkeypatch.setenv("MAILBOX_SERVICE_KEY_FILE", str(key_file))
    services = build_services(Settings())
    services.vault.initialize()
    create_account(
        services.accounts,
        ProviderType.MEMORY,
        "owner@example.com",
        credentials={"password": SecretStr("hunter2")},
    )
    master = services.vault.master_key()
    services.close()
    out = tmp_path / "out"
    made = {2: out / "two.bak", 3: out / "three.bak", 1: out / "one.bak"}
    assert main(["backup", str(made[2])]) == 0
    assert main(["backup", str(made[3]), "--format", "3"]) == 0
    _version_1(Settings().database_path, master, made[1])
    password = tmp_path / "database_password"
    password.write_text("unused", encoding="utf-8")
    monkeypatch.setenv("MAILBOX_SERVICE_STORAGE", "postgres")
    monkeypatch.setenv(
        "MAILBOX_SERVICE_DATABASE_URL", "postgresql://svc@db.example.org/mailbox"
    )
    monkeypatch.setenv("MAILBOX_SERVICE_DATABASE_PASSWORD_FILE", str(password))
    return made


@pytest.mark.parametrize("format", [1, 2, 3])
def test_a_check_writes_no_file(
    backups: dict[int, Path],
    tmp_path: Path,
    capsys: pytest.CaptureFixture[str],
    monkeypatch: pytest.MonkeyPatch,
    format: int,
) -> None:
    """Not even one removed after: no file is made for the check."""
    capsys.readouterr()
    before = _files(tmp_path)
    made: list[Path] = []
    monkeypatch.setattr(backup_module, "create_private", made.append)
    assert main(["backup", "verify", str(backups[format])]) == 0
    assert f", format {format}, " in capsys.readouterr().err
    assert _files(tmp_path) == before
    assert made == []


@pytest.mark.parametrize("format", [1, 2, 3])
def test_a_changed_backup_is_found(
    backups: dict[int, Path], capsys: pytest.CaptureFixture[str], format: int
) -> None:
    path = backups[format]
    data = bytearray(path.read_bytes())
    data[-40] ^= 0x01
    path.write_bytes(bytes(data))
    capsys.readouterr()
    assert main(["backup", "verify", str(path)]) == 1
    assert "does not decrypt" in capsys.readouterr().err


@pytest.mark.parametrize("format", [1, 2])
def test_a_file_backup_is_not_restored_on_a_server(
    backups: dict[int, Path], capsys: pytest.CaptureFixture[str], format: int
) -> None:
    """Before the server is reached: the two steps it takes instead."""
    capsys.readouterr()
    assert main(["restore", str(backups[format])]) == 1
    err = capsys.readouterr().err
    assert "MAILBOX_SERVICE_STORAGE=sqlite" in err
    assert "storage move --to postgres" in err
