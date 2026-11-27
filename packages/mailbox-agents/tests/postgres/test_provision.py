"""``storage provision --apply`` on the server: the role and the database
of an instance made as the administrator, and the roles of the cockpit
where they are missing. The agent then starts on it without another
step, and a second run refuses to make them again."""

from __future__ import annotations

import secrets
from collections.abc import Iterator
from pathlib import Path

import pytest

from benethos_mailbox_agents.cli import main
from benethos_mailbox_agents.cli.storage import LOGIN, READER
from benethos_mailbox_agents.settings import PREFIX, load_settings
from benethos_mailbox_agents.store import Store

from ..postgres_helpers import admin_password_file, admin_url, connect, fresh_name


@pytest.fixture
def named(monkeypatch: pytest.MonkeyPatch, tmp_path: Path) -> Iterator[str]:
    """Settings of a state on the server under a new name, its role and
    database gone after the test, the roles of the cockpit too."""
    from psycopg import sql

    name = fresh_name()
    password = tmp_path / "database_password"
    # Quotes and a percent sign, as a statement that makes a role takes
    # its password as a constant.
    password.write_text(f"it's 100% {secrets.token_hex(8)}", encoding="utf-8")
    host = admin_url().split("@", 1)[1].rsplit("/", 1)[0]
    monkeypatch.setenv(f"{PREFIX}STORAGE", "postgres")
    monkeypatch.setenv(f"{PREFIX}DATABASE_URL", f"postgresql://{name}@{host}/{name}")
    monkeypatch.setenv(f"{PREFIX}DATABASE_PASSWORD_FILE", str(password))
    monkeypatch.setenv(f"{PREFIX}DATABASE_READERS", READER)
    try:
        yield name
    finally:
        made = sql.Identifier(name)
        with connect() as conn:
            conn.execute(
                sql.SQL("DROP DATABASE IF EXISTS {} WITH (FORCE)").format(made)
            )
            conn.execute(sql.SQL("DROP ROLE IF EXISTS {}").format(made))
            for role in (LOGIN, READER):
                conn.execute(
                    sql.SQL("DROP ROLE IF EXISTS {}").format(sql.Identifier(role))
                )


def _apply(tmp_path: Path) -> int:
    return main(
        [
            *("storage", "provision", "--agent", "counting", "--apply"),
            *("--admin-url", admin_url()),
            *("--admin-password-file", str(admin_password_file(tmp_path))),
        ]
    )


def test_the_agent_starts_on_what_provision_made(
    named: str, tmp_path: Path, capsys: pytest.CaptureFixture[str]
) -> None:
    assert _apply(tmp_path) == 0
    said = capsys.readouterr().out
    assert f"made role {named}, database {named}, role {READER}, role {LOGIN}" in said

    settings = load_settings()
    with Store.open_server(
        settings.database_server(), readers=tuple(settings.database_readers)
    ) as store:
        assert store.rights is not None
        assert (store.rights.owner, store.rights.readers) == (True, (READER,))

    assert _apply(tmp_path) == 1
    assert "exist already" in capsys.readouterr().err
