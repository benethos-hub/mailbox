"""``storage move`` on the server: a filled state file goes into the
database of the instance, every table with the same rows, and the agent
starts on it. A database that holds the state already is refused, and so
is a file a running agent holds."""

from __future__ import annotations

from collections.abc import Iterator
from datetime import UTC, datetime
from pathlib import Path

import pytest

from benethos_mailbox_agents.cli import main
from benethos_mailbox_agents.records import MessageRef, StepResult
from benethos_mailbox_agents.settings import PREFIX
from benethos_mailbox_agents.store import Store, path_for
from benethos_mailbox_common.storage.server_place import Server

from ..postgres_helpers import instance

NOW = datetime(2026, 11, 27, 9, 0, tzinfo=UTC)


@pytest.fixture
def server(monkeypatch: pytest.MonkeyPatch, tmp_path: Path) -> Iterator[Server]:
    """The settings of a state file of counting and of a database of its
    own on the server, as a move takes them."""
    with instance() as found:
        password = tmp_path / "database_password"
        password.write_text(found.password, encoding="utf-8")
        monkeypatch.setenv(f"{PREFIX}DATA_DIR", str(tmp_path / "data"))
        monkeypatch.setenv(
            f"{PREFIX}DATABASE_URL",
            f"postgresql://{found.role}@{found.host}:{found.port}/{found.database}",
        )
        monkeypatch.setenv(f"{PREFIX}DATABASE_PASSWORD_FILE", str(password))
        yield found


def _filled(tmp_path: Path) -> Path:
    path = path_for(tmp_path / "data", "counting")
    with Store.open(path) as store:
        for n in range(3):
            ref = MessageRef(account_id="acc", message_id=f"m{n}")
            store.enqueue(ref, NOW)
            store.add_step(
                ref, StepResult(step="decision", result={"n": n}, at=NOW), "alias"
            )
        store.set_state(MessageRef(account_id="acc", message_id="m0"), "done", NOW)
    return path


def _move(*more: str) -> int:
    return main(["storage", "move", "--agent", "counting", *more])


def test_a_filled_file_moves_and_the_agent_starts_on_it(
    server: Server, tmp_path: Path, capsys: pytest.CaptureFixture[str]
) -> None:
    path = _filled(tmp_path)
    with Store.open(path, read_only=True) as before:
        counts = before.counts()

    assert _move("--check") == 0
    assert "Nothing was written" in capsys.readouterr().out
    assert _move() == 0

    said = capsys.readouterr().out
    assert f"to the database {server.database}" in said
    assert "compared table by table" in said
    with Store.open_server(server) as moved:
        assert moved.counts() == counts
        assert len(moved.due(NOW, 10)) == 2


def test_a_database_that_holds_the_state_is_refused(
    server: Server, tmp_path: Path, capsys: pytest.CaptureFixture[str]
) -> None:
    _filled(tmp_path)
    assert _move() == 0
    capsys.readouterr()

    assert _move() == 1
    assert "holds tables" in capsys.readouterr().err


def test_a_file_a_running_agent_holds_is_refused(
    server: Server, tmp_path: Path, capsys: pytest.CaptureFixture[str]
) -> None:
    with Store.open(_filled(tmp_path)):
        assert _move() == 1

    assert "running on this database: stop it first" in capsys.readouterr().err
