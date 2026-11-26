"""The settings of a database on a server: each rule is named by its
setting, never with what was given, and the password of the role is read
from its file and kept from every log line."""

from __future__ import annotations

from pathlib import Path

import pytest

from benethos_mailbox_common.log import redact
from benethos_mailbox_service.assembly.storage import server_of
from benethos_mailbox_service.cli import main
from benethos_mailbox_service.config import Settings, load_settings

PASSWORD = "an-invented-role-password"  # pragma: allowlist secret


@pytest.fixture
def password_file(tmp_path: Path) -> Path:
    path = tmp_path / "database_password"
    path.write_text(PASSWORD + "\n", encoding="utf-8")
    return path


@pytest.mark.parametrize(
    ("url", "rule"),
    [
        (None, "needs database_url and database_password_file"),
        ("mysql://svc@db.example.org:5432/mailbox", "must have the form"),
        ("postgresql://db.example.org:5432/mailbox", "must have the form"),
        ("postgresql://svc@db.example.org:5432/", "must have the form"),
        ("postgresql://svc@db.example.org:port/mailbox", "must have the form"),
        (
            "postgresql://svc:" + PASSWORD + "@db.example.org:5432/mailbox",
            "must not hold a password",
        ),
        ("postgresql://Svc-1@db.example.org:5432/mailbox", "lower case letters"),
    ],
    ids=[
        "no url",
        "another scheme",
        "no role",
        "no database",
        "no port",
        "a password",
        "no plain role",
    ],
)
def test_a_rule_of_the_database_is_named_without_the_value(
    monkeypatch: pytest.MonkeyPatch,
    capsys: pytest.CaptureFixture[str],
    password_file: Path,
    url: str | None,
    rule: str,
) -> None:
    monkeypatch.setenv("MAILBOX_SERVICE_STORAGE", "postgres")
    monkeypatch.setenv("MAILBOX_SERVICE_DATABASE_PASSWORD_FILE", str(password_file))
    if url is not None:
        monkeypatch.setenv("MAILBOX_SERVICE_DATABASE_URL", url)
    assert main(["paths"]) == 1
    err = capsys.readouterr().err
    assert err.startswith("error: wrong settings: ")
    assert rule in err
    assert PASSWORD not in err
    assert "db.example.org" not in err


def test_a_password_file_is_needed(monkeypatch: pytest.MonkeyPatch) -> None:
    with pytest.raises(ValueError, match="database_password_file"):
        Settings(
            _env_file=None,  # type: ignore[call-arg]
            storage="postgres",
            database_url="postgresql://svc@db.example.org:5432/mailbox",
        )


def test_the_server_comes_from_the_settings(password_file: Path) -> None:
    settings = Settings(
        _env_file=None,  # type: ignore[call-arg]
        storage="postgres",
        database_url="postgresql://svc@db.example.org:5433/mailbox",
        database_password_file=password_file,
    )
    server = server_of(settings)
    assert server is not None
    assert (server.host, server.port, server.database, server.role) == (
        "db.example.org",
        5433,
        "mailbox",
        "svc",
    )
    assert server.schema_name == "svc"
    assert server.password == PASSWORD
    assert PASSWORD not in repr(server)
    assert PASSWORD not in redact.redact(f"a line with {PASSWORD} in it")


def test_another_storage_has_no_server() -> None:
    assert server_of(Settings(_env_file=None)) is None  # type: ignore[call-arg]


def test_the_files_count_from_a_named_settings_file(tmp_path: Path) -> None:
    named = tmp_path / "service.env"
    named.write_text(
        "MAILBOX_SERVICE_STORAGE=postgres\n"
        "MAILBOX_SERVICE_DATABASE_URL=postgresql://svc@db.example.org/mailbox\n"
        "MAILBOX_SERVICE_DATABASE_PASSWORD_FILE=secrets/database_password\n"
        "MAILBOX_SERVICE_DATABASE_CA_FILE=secrets/ca.pem\n",
        encoding="utf-8",
    )
    (tmp_path / "secrets").mkdir()
    (tmp_path / "secrets" / "database_password").write_text(PASSWORD, "utf-8")
    settings = load_settings(named)
    assert settings.database_password_file == (
        tmp_path / "secrets" / "database_password"
    )
    assert settings.database_ca_file == tmp_path / "secrets" / "ca.pem"
    assert settings.database_password().get_secret_value() == PASSWORD


def test_paths_names_the_server_and_never_the_password(
    monkeypatch: pytest.MonkeyPatch,
    capsys: pytest.CaptureFixture[str],
    password_file: Path,
) -> None:
    url = "postgresql://svc@db.example.org:5432/mailbox"
    monkeypatch.setenv("MAILBOX_SERVICE_STORAGE", "postgres")
    monkeypatch.setenv("MAILBOX_SERVICE_DATABASE_URL", url)
    monkeypatch.setenv("MAILBOX_SERVICE_DATABASE_PASSWORD_FILE", str(password_file))
    assert main(["paths"]) == 0
    out = capsys.readouterr().out
    assert f"Database:      {url}" in out.splitlines()
    assert PASSWORD not in out
