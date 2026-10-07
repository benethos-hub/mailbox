"""Backup and restore of the database: round trips, a running service,
the commands."""

from __future__ import annotations

import io
import re
import sqlite3
from pathlib import Path

import pytest
from fastapi.testclient import TestClient
from pydantic import SecretStr

from benethos_mailbox_service.assembly import Services, build_services, create_app
from benethos_mailbox_service.cli import main
from benethos_mailbox_service.config import Settings
from benethos_mailbox_service.data import backup
from benethos_mailbox_service.data.backup import (
    MAGIC,
    BackupError,
    create_backup,
    read_backup,
    restore_backup,
    verify_backup,
)
from benethos_mailbox_service.data.models import ProviderType
from benethos_mailbox_service.data.secrets import (
    FileKeyProvider,
    cipher,
    decode_recovery,
)
from benethos_mailbox_service.data.storage import (
    Repositories,
)

from ..conftest import create_account


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
    assert services.store is not None
    master = services.vault.master_key()
    manifest = create_backup(services.store, master, machine / "b.bak", "9.9.9")
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


def test_restore_moves_a_leftover_journal_with_the_old_file(machine: Path) -> None:
    _populate()
    services = _services()
    assert services.store is not None
    master = services.vault.master_key()
    create_backup(services.store, master, machine / "b.bak", "9.9.9")
    services.close()
    path = Settings().database_path
    journal = path.with_name(path.name + "-journal")
    journal.write_bytes(b"hot journal of the old file")

    restore_backup(machine / "b.bak", master, path)
    assert not journal.exists()
    [moved] = list(path.parent.glob("mailbox.db.before-restore-*-journal"))
    assert moved.read_bytes() == b"hot journal of the old file"
    restored = _services()
    assert len(restored.adapters.ids()) == 1
    restored.close()


def _backed_up(machine: Path) -> tuple[bytes, Path]:
    """The master key and a database with one account, backed up."""
    _populate()
    services = _services()
    assert services.store is not None
    master = services.vault.master_key()
    create_backup(services.store, master, machine / "b.bak", "9.9.9")
    services.close()
    return master, Settings().database_path


def test_restore_refuses_while_the_service_runs(machine: Path) -> None:
    master, path = _backed_up(machine)
    before = path.read_bytes()
    running = _services()
    assert running.store is not None
    with running.store.serving() as held:
        assert held
        with pytest.raises(BackupError, match="the service is running"):
            restore_backup(machine / "b.bak", master, path)
    running.close()
    assert path.read_bytes() == before
    assert list(path.parent.glob("mailbox.db.before-restore-*")) == []
    # Stopped, the restore goes through.
    restore_backup(machine / "b.bak", master, path)


def test_the_app_marks_its_database_while_it_serves(machine: Path) -> None:
    master, path = _backed_up(machine)
    with TestClient(create_app(Settings())) as client:
        assert client.get("/health").status_code == 200
        with pytest.raises(BackupError, match="the service is running"):
            restore_backup(machine / "b.bak", master, path)
    restore_backup(machine / "b.bak", master, path)


def test_a_second_service_on_the_database_is_noted(
    machine: Path, caplog: pytest.LogCaptureFixture
) -> None:
    _backed_up(machine)
    first = _services()
    assert first.store is not None
    with first.store.serving(), TestClient(create_app(Settings())):
        pass
    first.close()
    assert "found another service using this database" in caplog.text


def test_a_restore_that_fails_leaves_the_database_in_place(
    machine: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    master, path = _backed_up(machine)
    before = path.read_bytes()
    staged = path.with_name(path.name + ".restoring")
    staged.write_bytes(b"left by a restore that crashed")

    def broken(path: Path) -> None:
        raise sqlite3.OperationalError("disk I/O error")

    monkeypatch.setattr(backup, "migrate_file", broken)
    with pytest.raises(sqlite3.OperationalError):
        restore_backup(machine / "b.bak", master, path)
    assert path.read_bytes() == before
    assert not staged.exists()
    assert list(path.parent.glob("mailbox.db.before-restore-*")) == []


def test_backup_never_overwrites(machine: Path) -> None:
    _populate()
    services = _services()
    assert services.store is not None
    (machine / "b.bak").write_bytes(b"x")
    with pytest.raises(BackupError, match="refusing"):
        create_backup(
            services.store, services.vault.master_key(), machine / "b.bak", "1"
        )
    services.close()


def _backup_file(machine: Path) -> tuple[Path, bytes]:
    _populate()
    services = _services()
    assert services.store is not None
    master = services.vault.master_key()
    create_backup(services.store, master, machine / "b.bak", "1")
    services.close()
    return machine / "b.bak", master


def test_wrong_key_does_not_open(machine: Path) -> None:
    path, _ = _backup_file(machine)
    with pytest.raises(BackupError, match="does not decrypt"):
        read_backup(path, cipher.new_key(), machine / "out.db")
    assert not (machine / "out.db").exists()


def test_altered_manifest_is_detected(machine: Path) -> None:
    path, master = _backup_file(machine)
    raw = path.read_bytes()
    path.write_bytes(raw.replace(b'"service_version": "1"', b'"service_version": "2"'))
    with pytest.raises(BackupError, match="does not decrypt"):
        read_backup(path, master, machine / "out.db")


def test_the_copy_of_a_backup_is_gone_afterwards(machine: Path) -> None:
    path, master = _backup_file(machine)
    folder = Settings().database_path.parent
    # Only the lock stays, which holds nothing.
    assert list(folder.glob("*.snapshot*")) == [folder / "mailbox.db.snapshot.lock"]
    scratch = folder / "check.db"
    verify_backup(path, master, scratch)
    assert not scratch.exists()


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
    # The time of the backup as every line writes a time (LOGGING.md 6.9).
    assert re.search(
        r"Restored the backup of \d{4}-\d\d-\d\dT\d\d:\d\d:\d\d\.\d{3}[+-]\d\d:\d\d\.",
        capsys.readouterr().err,
    )
    assert FileKeyProvider(new_key_file).load() == decode_recovery(recovery)
    services = _services()
    assert services.vault.read(account_id, "password").get_secret_value() == "hunter2"
    services.close()

    monkeypatch.setattr("sys.stdin", _Stdin(recovery + "\n"))
    assert main(["backup", "verify", str(target), "--recovery-key"]) == 0

    # Writing a backup takes the master key the service holds: the option
    # belongs to verify alone, and is refused rather than ignored.
    assert main(["backup", str(target), "--recovery-key"]) == 1
    assert "goes with `backup verify FILE`" in capsys.readouterr().err


def test_a_restore_keeps_another_master_key_unless_told(
    machine: Path,
    monkeypatch: pytest.MonkeyPatch,
    capsys: pytest.CaptureFixture[str],
) -> None:
    account_id, recovery = _populate()
    target = machine / "mailbox.bak"
    assert main(["backup", str(target)]) == 0

    # Another machine with a database and a master key of its own.
    monkeypatch.setenv("MAILBOX_SERVICE_DATA_DIR", str(machine / "other-data"))
    other_key_file = machine / "other-secret" / "master.key"
    monkeypatch.setenv("MAILBOX_SERVICE_KEY_FILE", str(other_key_file))
    assert main(["keys", "init"]) == 0
    out, err = capsys.readouterr()
    assert "Keys created" in err
    assert len(out.split()) == 1, "stdout holds the recovery key alone"
    own = FileKeyProvider(other_key_file).load()
    before = Settings().database_path.read_bytes()
    capsys.readouterr()

    monkeypatch.setattr("sys.stdin", _Stdin(recovery + "\n"))
    assert main(["restore", str(target), "--recovery-key"]) == 1
    assert "holds another master key" in capsys.readouterr().err
    assert FileKeyProvider(other_key_file).load() == own
    assert Settings().database_path.read_bytes() == before

    assert main(["restore", str(target), "--replace-master-key"]) == 1
    assert "goes with --recovery-key" in capsys.readouterr().err

    monkeypatch.setattr("sys.stdin", _Stdin(recovery + "\n"))
    assert main(["restore", str(target), "--recovery-key", "--replace-master-key"]) == 0
    assert FileKeyProvider(other_key_file).load() == decode_recovery(recovery)
    services = _services()
    assert services.vault.read(account_id, "password").get_secret_value() == "hunter2"
    services.close()


def test_backup_command_errors(
    machine: Path,
    monkeypatch: pytest.MonkeyPatch,
    capsys: pytest.CaptureFixture[str],
) -> None:
    assert main(["backup", "a", "b"]) == 1
    assert "backup verify FILE" in capsys.readouterr().err
    assert main(["backup", "verify"]) == 1
    assert "backup verify FILE" in capsys.readouterr().err
    assert not (Path.cwd() / "verify").exists()
    assert main(["backup", str(machine / "x.bak")]) == 1
    assert "keys init" in capsys.readouterr().err
    monkeypatch.setenv("MAILBOX_SERVICE_STORAGE", "memory")
    assert main(["backup", str(machine / "x.bak")]) == 1
    assert "MAILBOX_SERVICE_STORAGE=sqlite" in capsys.readouterr().err


def test_files_that_cannot_be_read_or_written(
    machine: Path, capsys: pytest.CaptureFixture[str]
) -> None:
    _populate()
    assert main(["backup", "verify", str(machine / "missing.bak")]) == 1
    assert "missing.bak cannot be read" in capsys.readouterr().err
    blocker = machine / "a-file"
    blocker.write_text("")
    assert main(["backup", str(blocker / "mailbox.bak")]) == 1
    assert "mailbox.bak cannot be written" in capsys.readouterr().err


def test_a_client_secret_file_that_is_missing(
    machine: Path,
    monkeypatch: pytest.MonkeyPatch,
    capsys: pytest.CaptureFixture[str],
) -> None:
    missing = machine / "no-such-secret"
    monkeypatch.setenv("MAILBOX_SERVICE_OAUTH_MICROSOFT_CLIENT_ID", "client-1")
    monkeypatch.setenv(
        "MAILBOX_SERVICE_OAUTH_MICROSOFT_CLIENT_SECRET_FILE", str(missing)
    )

    def never(*args: object, **kwargs: object) -> None:
        raise AssertionError("the service must not start")

    monkeypatch.setattr("uvicorn.run", never)
    closed: list[Repositories] = []
    close = Repositories.close

    def closing(self: Repositories) -> None:
        closed.append(self)
        close(self)

    monkeypatch.setattr(Repositories, "close", closing)
    assert main(["serve"]) == 1
    assert "no-such-secret" in capsys.readouterr().err
    # The database it opened before is closed again.
    assert len(closed) == 1
