"""The command ``storage move`` against the server: to PostgreSQL and
back, the check, and a running service on either side refuses it. A
second ``serve`` on the schema ends with the reason, without a
traceback."""

from __future__ import annotations

from collections.abc import Iterator
from pathlib import Path

import pytest
from pydantic import SecretStr

from benethos_mailbox_service.assembly import build_services
from benethos_mailbox_service.cli import main
from benethos_mailbox_service.config import Settings
from benethos_mailbox_service.data.models import ProviderType
from benethos_mailbox_service.data.storage import Database, Server, ServerPlace

from ..conftest import create_account
from ..postgres_helpers import admin, role


@pytest.fixture
def host(tmp_path: Path, monkeypatch: pytest.MonkeyPatch) -> Iterator[Server]:
    """A service on SQLite with one account, and the settings of a role
    of its own on the server, whose schema is empty."""
    with role() as server:
        password = tmp_path / "database_password"
        password.write_text(server.password, encoding="utf-8")
        who = admin()
        monkeypatch.setenv("MAILBOX_SERVICE_DATA_DIR", str(tmp_path / "data"))
        monkeypatch.setenv("MAILBOX_SERVICE_STORAGE", "sqlite")
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


def test_a_move_to_postgres_and_back(
    host: Server, tmp_path: Path, capsys: pytest.CaptureFixture[str]
) -> None:
    assert main(["storage", "move", "--to", "postgres", "--check"]) == 0
    assert "Nothing was written." in capsys.readouterr().err
    assert main(["storage", "move", "--to", "postgres"]) == 0
    assert "MAILBOX_SERVICE_STORAGE=postgres" in capsys.readouterr().err
    on_server = Database(place=ServerPlace(host))
    try:
        assert len(list(on_server.rows("accounts"))) == 1
    finally:
        on_server.close()
    (tmp_path / "data" / "mailbox.db").rename(tmp_path / "data" / "before.db")
    assert main(["storage", "move", "--to", "sqlite"]) == 0
    assert (tmp_path / "data" / "mailbox.db").exists()


def test_a_running_service_on_either_side_refuses(
    host: Server, tmp_path: Path, capsys: pytest.CaptureFixture[str]
) -> None:
    running = Database(tmp_path / "data" / "mailbox.db")
    with running.serving():
        assert main(["storage", "move", "--to", "postgres"]) == 1
        assert "the service is running" in capsys.readouterr().err
    running.close()
    assert main(["storage", "move", "--to", "postgres"]) == 0
    (tmp_path / "data" / "mailbox.db").rename(tmp_path / "data" / "before.db")
    on_server = Database(place=ServerPlace(host))
    try:
        with on_server.serving():
            assert main(["storage", "move", "--to", "sqlite"]) == 1
            assert "the service is running" in capsys.readouterr().err
    finally:
        on_server.close()


def test_a_second_serve_on_the_schema_ends_without_a_traceback(
    host: Server, monkeypatch: pytest.MonkeyPatch, capsys: pytest.CaptureFixture[str]
) -> None:
    import uvicorn

    def never(*args: object, **kwargs: object) -> None:
        raise AssertionError("the second service must not start")

    monkeypatch.setattr(uvicorn.Server, "run", never)
    monkeypatch.setenv("MAILBOX_SERVICE_STORAGE", "postgres")
    running = Database(place=ServerPlace(host))
    try:
        with running.serving():
            assert main(["serve"]) == 1
    finally:
        running.close()
    err = capsys.readouterr().err
    assert "error: another service runs on this database" in err
    assert "Traceback" not in err
