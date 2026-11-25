"""The commands of backups in both formats: written, verified and
restored, and the format named in each answer."""

from __future__ import annotations

from pathlib import Path

import pytest
from pydantic import SecretStr

from benethos_mailbox_service.assembly import build_services
from benethos_mailbox_service.cli import main
from benethos_mailbox_service.config import Settings
from benethos_mailbox_service.data.backup import MAGIC, MAGIC_3
from benethos_mailbox_service.data.models import ProviderType

from ..conftest import create_account


@pytest.fixture
def host(tmp_path: Path, monkeypatch: pytest.MonkeyPatch) -> Path:
    """SQLite storage, a key file, and one account with a password."""
    monkeypatch.setenv("MAILBOX_SERVICE_DATA_DIR", str(tmp_path / "data"))
    monkeypatch.setenv("MAILBOX_SERVICE_STORAGE", "sqlite")
    monkeypatch.setenv("MAILBOX_SERVICE_KEY_PROVIDER", "file")
    monkeypatch.setenv(
        "MAILBOX_SERVICE_KEY_FILE", str(tmp_path / "secret" / "master.key")
    )
    services = build_services(Settings())
    services.vault.initialize()
    create_account(
        services.accounts,
        ProviderType.MEMORY,
        "owner@example.com",
        credentials={"password": SecretStr("hunter2")},
    )
    services.close()
    return tmp_path


@pytest.mark.parametrize(
    ("given", "format", "magic"),
    [([], 2, MAGIC), (["--format", "2"], 2, MAGIC), (["--format", "3"], 3, MAGIC_3)],
)
def test_each_format_is_written_verified_and_restored(
    host: Path,
    capsys: pytest.CaptureFixture[str],
    given: list[str],
    format: int,
    magic: bytes,
) -> None:
    target = host / "out" / "mailbox.bak"
    assert main(["backup", str(target), *given]) == 0
    assert f"Backup written in format {format}:" in capsys.readouterr().err
    assert target.read_bytes().startswith(magic)
    assert main(["backup", "verify", str(target)]) == 0
    assert f", format {format}, " in capsys.readouterr().err
    assert main(["restore", str(target)]) == 0
    assert f"It is of format {format}." in capsys.readouterr().err
    services = build_services(Settings())
    [account] = services.adapters.ids()
    assert services.vault.read(account, "password").get_secret_value() == "hunter2"
    services.close()


def test_a_format_it_does_not_know_is_a_usage_error(
    host: Path, capsys: pytest.CaptureFixture[str]
) -> None:
    with pytest.raises(SystemExit) as ended:
        main(["backup", str(host / "b.bak"), "--format", "4"])
    assert ended.value.code == 2
    assert not (host / "b.bak").exists()
    assert main(["backup", "verify", str(host / "b.bak"), "--format", "3"]) == 1
    assert "--format goes with `backup FILE`" in capsys.readouterr().err
