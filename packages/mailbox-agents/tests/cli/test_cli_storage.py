"""``storage provision`` without a server: the statements it prints for
an instance, the names it takes or suggests, and what ``--apply``
needs."""

from __future__ import annotations

import pytest

from benethos_mailbox_agents.cli import main
from benethos_mailbox_agents.cli.storage import suggested_name
from benethos_mailbox_agents.errors import ConfigError
from benethos_mailbox_agents.settings import PREFIX


def _plan(capsys: pytest.CaptureFixture[str], agent: str) -> list[str]:
    assert main(["storage", "provision", "--agent", agent]) == 0
    return capsys.readouterr().out.splitlines()


def test_the_statements_of_two_instances(
    monkeypatch: pytest.MonkeyPatch, capsys: pytest.CaptureFixture[str]
) -> None:
    first = _plan(capsys, "counting")
    monkeypatch.setenv(f"{PREFIX}INSTANCE", "partner-a")
    second = _plan(capsys, "categorization")

    assert first[:3] == [
        "CREATE ROLE agent_counting LOGIN NOSUPERUSER NOCREATEDB NOCREATEROLE"
        " NOINHERIT;",
        "CREATE DATABASE agent_counting OWNER agent_counting;",
        "REVOKE CONNECT, TEMPORARY ON DATABASE agent_counting FROM PUBLIC;",
    ]
    assert second[1] == (
        "CREATE DATABASE agent_categorization_partner_a"
        " OWNER agent_categorization_partner_a;"
    )
    assert first[3:6] == second[3:6]
    assert first[4:6] == [
        "CREATE ROLE agents_read NOLOGIN NOSUPERUSER NOCREATEDB NOCREATEROLE;",
        "CREATE ROLE agents_cockpit LOGIN NOSUPERUSER NOCREATEDB NOCREATEROLE"
        " IN ROLE agents_read;",
    ]
    assert (
        f"--   {PREFIX}DATABASE_URL=postgresql://agent_counting@<host>:<port>"
        "/agent_counting"
    ) in first
    assert not [line for line in first + second if " PASSWORD " in line]


def test_the_names_of_the_database_url_are_taken(
    monkeypatch: pytest.MonkeyPatch, capsys: pytest.CaptureFixture[str]
) -> None:
    monkeypatch.setenv(
        f"{PREFIX}DATABASE_URL", "postgresql://counting_one@db.example.org:5433/mine"
    )

    found = _plan(capsys, "counting")

    assert found[1] == "CREATE DATABASE mine OWNER counting_one;"
    assert (
        f"--   {PREFIX}DATABASE_URL=postgresql://counting_one@db.example.org:5433/mine"
    ) in found


def test_a_name_longer_than_postgresql_takes_is_refused() -> None:
    assert suggested_name("awaiting_reply", "a" * 40) == (
        "agent_awaiting_reply_" + "a" * 40
    )
    with pytest.raises(ConfigError, match="longer than the 63 characters"):
        suggested_name("awaiting_reply", "a" * 43)


@pytest.mark.parametrize(
    ("given", "said"),
    [
        ([], "--apply needs --admin-url and --admin-password-file"),
        (
            ["--admin-url", "postgresql://postgres@db.example.org/postgres"],
            "--apply needs --admin-url and --admin-password-file",
        ),
        (
            ["--admin-url", "x", "--admin-password-file", "pw"],
            f"set {PREFIX}STORAGE=postgres",
        ),
    ],
)
def test_apply_needs_an_administrator_and_a_server(
    capsys: pytest.CaptureFixture[str], given: list[str], said: str
) -> None:
    argv = ["storage", "provision", "--agent", "counting", "--apply", *given]

    assert main(argv) == 2

    assert said in capsys.readouterr().err
