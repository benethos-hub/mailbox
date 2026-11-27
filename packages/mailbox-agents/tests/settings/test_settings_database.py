"""The settings of a state on a PostgreSQL server."""

from __future__ import annotations

from pathlib import Path

import pytest

from benethos_mailbox_agents import errors
from benethos_mailbox_agents.settings import PREFIX, load_settings
from benethos_mailbox_common.log import redact

URL = "postgresql://agent_counting@db.example.org:5432/agent_counting"
PASSWORD = "role-password-value"  # pragma: allowlist secret


@pytest.fixture
def on_a_server(monkeypatch: pytest.MonkeyPatch, tmp_path: Path) -> Path:
    password = tmp_path / "database_password"
    password.write_text(PASSWORD + "\n", encoding="utf-8")
    monkeypatch.setenv(f"{PREFIX}STORAGE", "postgres")
    monkeypatch.setenv(f"{PREFIX}DATABASE_URL", URL)
    monkeypatch.setenv(f"{PREFIX}DATABASE_PASSWORD_FILE", str(password))
    return password


def test_the_state_is_a_file_by_default() -> None:
    found = load_settings()

    assert (found.storage, found.database_url, found.database_readers) == (
        "sqlite",
        None,
        [],
    )


def test_the_server_is_named_and_its_password_masked(
    on_a_server: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    monkeypatch.setenv(f"{PREFIX}DATABASE_READERS", "agents_read")

    found = load_settings()
    server = found.database_server()

    assert (server.host, server.port, server.database, server.role) == (
        "db.example.org",
        5432,
        "agent_counting",
        "agent_counting",
    )
    assert found.database_readers == ["agents_read"]
    assert redact.redact(f"x {PASSWORD}") == "x ***"
    assert PASSWORD not in repr(server)


@pytest.mark.parametrize(
    ("name", "value", "said"),
    [
        ("DATABASE_URL", "postgresql://role:pw@db.example.org/db", "password"),
        ("DATABASE_URL", "mysql://role@db.example.org/db", "must have the form"),
        ("DATABASE_URL", "postgresql://Role@db.example.org/db", "lower case"),
        ("DATABASE_READERS", "agents-read", "database_readers"),
        ("PROMPT_RETENTION_DAYS", "3", "prompt_retention_days"),
    ],
)
def test_what_does_not_fit_a_server_is_refused_by_its_rule(
    on_a_server: Path,
    monkeypatch: pytest.MonkeyPatch,
    name: str,
    value: str,
    said: str,
) -> None:
    monkeypatch.setenv(f"{PREFIX}{name}", value)

    with pytest.raises(errors.ConfigError, match=said) as raised:
        load_settings()

    assert ":pw@" not in raised.value.message


def test_without_its_password_file_a_server_is_refused(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    monkeypatch.setenv(f"{PREFIX}STORAGE", "postgres")
    monkeypatch.setenv(f"{PREFIX}DATABASE_URL", URL)

    with pytest.raises(errors.ConfigError, match="database_password_file"):
        load_settings()


def test_an_empty_password_file_stops_the_start(on_a_server: Path) -> None:
    on_a_server.write_text("\n", encoding="utf-8")

    with pytest.raises(errors.ConfigError, match="names an empty file"):
        load_settings().database_server()
