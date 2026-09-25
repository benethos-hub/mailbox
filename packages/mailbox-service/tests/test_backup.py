from __future__ import annotations

import io
import sqlite3
from pathlib import Path

import pytest
from pydantic import SecretStr

from benethos_mailbox_service.__main__ import main
from benethos_mailbox_service.config import Settings
from benethos_mailbox_service.data.models import ProviderType
from benethos_mailbox_service.data.secrets import (
    FileKeyProvider,
    cipher,
    decode_recovery,
)
from benethos_mailbox_service.data.secrets.backup import (
    MAGIC,
    BackupError,
    Manifest,
    create_backup,
    read_backup,
    restore_backup,
    write_backup,
)
from benethos_mailbox_service.data.storage import Database, inspect_snapshot
from benethos_mailbox_service.main import Services, build_services

from .conftest import create_account


class _Stdin(io.StringIO):
    def isatty(self) -> bool:
        return False


@pytest.fixture
def machine(tmp_path: Path, monkeypatch: pytest.MonkeyPatch) -> Path:
    """A host with SQLite storage and a key file, keys initialised."""
    monkeypatch.setenv("MAILBOX_SERVICE_DATA_DIR", str(tmp_path / "data"))
    monkeypatch.setenv("MAILBOX_SERVICE_STORAGE", "sqlite")
    monkeypatch.setenv("MAILBOX_SERVICE_KEY_PROVIDER", "file")
    monkeypatch.setenv(
        "MAILBOX_SERVICE_KEY_FILE", str(tmp_path / "secret" / "master.key")
    )
    return tmp_path


def _services() -> Services:
    return build_services(Settings())


def _populate() -> tuple[str, str]:
    services = _services()
    recovery = services.vault.initialize()
    account = create_account(
        services.accounts,
        ProviderType.MEMORY,
        "owner@example.com",
        credentials={"password": SecretStr("hunter2")},
    )
    services.close()
    return account.id, recovery


def test_backup_and_restore_round_trip(machine: Path) -> None:
    account_id, _ = _populate()
    services = _services()
    assert services.database is not None
    master = services.vault.master_key()
    manifest = create_backup(services.database, master, machine / "b.bak", "9.9.9")
    create_account(services.accounts, ProviderType.MEMORY, "later@example.com")
    services.close()

    assert manifest.service_version == "9.9.9"
    raw = (machine / "b.bak").read_bytes()
    assert raw.startswith(MAGIC)
    assert b"owner@example.com" not in raw
    assert b"hunter2" not in raw

    restore_backup(machine / "b.bak", master, Settings().database_path)
    restored = _services()
    ids = restored.adapters.ids()
    assert ids == [account_id]
    assert restored.vault.read(account_id, "password").get_secret_value() == "hunter2"
    restored.close()
    kept = list(Settings().database_path.parent.glob("mailbox.db.before-restore-*"))
    assert len(kept) == 1


def test_backup_never_overwrites(machine: Path) -> None:
    _populate()
    services = _services()
    assert services.database is not None
    (machine / "b.bak").write_bytes(b"x")
    with pytest.raises(BackupError, match="refusing"):
        create_backup(
            services.database, services.vault.master_key(), machine / "b.bak", "1"
        )
    services.close()


def _backup_file(machine: Path) -> tuple[Path, bytes]:
    _populate()
    services = _services()
    assert services.database is not None
    master = services.vault.master_key()
    create_backup(services.database, master, machine / "b.bak", "1")
    services.close()
    return machine / "b.bak", master


def test_wrong_key_does_not_open(machine: Path) -> None:
    path, _ = _backup_file(machine)
    with pytest.raises(BackupError, match="does not decrypt"):
        read_backup(path, cipher.new_key())


def test_altered_manifest_is_detected(machine: Path) -> None:
    path, master = _backup_file(machine)
    raw = path.read_bytes()
    path.write_bytes(raw.replace(b'"service_version": "1"', b'"service_version": "2"'))
    with pytest.raises(BackupError, match="does not decrypt"):
        read_backup(path, master)


@pytest.mark.parametrize(
    ("content", "message"),
    [
        (b"hello", "not a backup"),
        (MAGIC + b"no newline", "truncated"),
        (MAGIC + b"{not json}\n", "unreadable manifest"),
    ],
)
def test_broken_files(tmp_path: Path, content: bytes, message: str) -> None:
    path = tmp_path / "broken.bak"
    path.write_bytes(content)
    with pytest.raises(BackupError, match=message):
        read_backup(path, cipher.new_key())


def test_checksum_and_schema_mismatch(tmp_path: Path) -> None:
    db = Database(tmp_path / "x.db")
    data = db.snapshot()
    db.close()
    master = cipher.new_key()
    bad_sum = Manifest("1", inspect_snapshot(data), "now", "0" * 64)
    write_backup(data, bad_sum, master, tmp_path / "sum.bak")
    with pytest.raises(BackupError, match="checksum"):
        read_backup(tmp_path / "sum.bak", master)

    import hashlib

    digest = hashlib.sha256(data).hexdigest()
    wrong_schema = Manifest("1", 42, "now", digest)
    write_backup(data, wrong_schema, master, tmp_path / "schema.bak")
    with pytest.raises(BackupError, match="does not match its manifest"):
        read_backup(tmp_path / "schema.bak", master)

    not_a_db = b"garbage" * 100
    write_backup(
        not_a_db,
        Manifest("1", 1, "now", hashlib.sha256(not_a_db).hexdigest()),
        master,
        tmp_path / "garbage.bak",
    )
    with pytest.raises(BackupError):
        read_backup(tmp_path / "garbage.bak", master)


def test_a_newer_schema_is_not_restored(tmp_path: Path) -> None:
    path = tmp_path / "future.db"
    Database(path).close()
    raw = sqlite3.connect(path)
    with raw:
        raw.execute("UPDATE meta SET value = '999' WHERE key = 'schema_version'")
    raw.close()
    data = path.read_bytes()
    master = cipher.new_key()
    import hashlib

    write_backup(
        data,
        Manifest("1", 999, "now", hashlib.sha256(data).hexdigest()),
        master,
        tmp_path / "future.bak",
    )
    with pytest.raises(BackupError, match="update the service"):
        restore_backup(tmp_path / "future.bak", master, tmp_path / "target.db")


def test_inspect_rejects_non_databases() -> None:
    with pytest.raises(ValueError):
        inspect_snapshot(b"not a database at all" * 50)


# --- the commands -------------------------------------------------------------


def test_backup_verify_restore_commands(
    machine: Path,
    monkeypatch: pytest.MonkeyPatch,
    capsys: pytest.CaptureFixture[str],
) -> None:
    account_id, recovery = _populate()
    target = machine / "out" / "mailbox.bak"
    assert main(["backup", str(target)]) == 0
    assert main(["backup", "verify", str(target)]) == 0
    assert "OK: backup of" in capsys.readouterr().err

    # A new machine: empty data directory, no key file.
    monkeypatch.setenv("MAILBOX_SERVICE_DATA_DIR", str(machine / "new-data"))
    new_key_file = machine / "new-secret" / "master.key"
    monkeypatch.setenv("MAILBOX_SERVICE_KEY_FILE", str(new_key_file))
    assert main(["restore", str(target)]) == 1
    assert "pass --recovery-key" in capsys.readouterr().err

    monkeypatch.setattr("sys.stdin", _Stdin(recovery + "\n"))
    assert main(["restore", str(target), "--recovery-key"]) == 0
    assert FileKeyProvider(new_key_file).load() == decode_recovery(recovery)
    services = _services()
    assert services.vault.read(account_id, "password").get_secret_value() == "hunter2"
    services.close()

    monkeypatch.setattr("sys.stdin", _Stdin(recovery + "\n"))
    assert main(["backup", "verify", str(target), "--recovery-key"]) == 0


def test_backup_command_errors(
    machine: Path,
    monkeypatch: pytest.MonkeyPatch,
    capsys: pytest.CaptureFixture[str],
) -> None:
    assert main(["backup", "a", "b"]) == 1
    assert "backup verify FILE" in capsys.readouterr().err
    assert main(["backup", str(machine / "x.bak")]) == 1
    assert "keys init" in capsys.readouterr().err
    monkeypatch.setenv("MAILBOX_SERVICE_STORAGE", "memory")
    assert main(["backup", str(machine / "x.bak")]) == 1
    assert "MAILBOX_SERVICE_STORAGE=sqlite" in capsys.readouterr().err
