"""``status``, ``paths``, ``health`` and ``report`` with the state on the
server: each reads it there and says where it lies, never a password,
and a database no agent started on yet is no state."""

from __future__ import annotations

from collections.abc import Iterator
from datetime import UTC, datetime
from pathlib import Path

import pytest

from benethos_mailbox_agents.cli import main
from benethos_mailbox_agents.records import MessageRef, Profile
from benethos_mailbox_agents.settings import PREFIX
from benethos_mailbox_agents.store import Store
from benethos_mailbox_common.storage.server_place import Server

from ..postgres_helpers import instance

NOW = datetime.now(UTC)


@pytest.fixture
def server(monkeypatch: pytest.MonkeyPatch, tmp_path: Path) -> Iterator[Server]:
    with instance() as found:
        password = tmp_path / "database_password"
        password.write_text(found.password, encoding="utf-8")
        monkeypatch.setenv(f"{PREFIX}STORAGE", "postgres")
        monkeypatch.setenv(
            f"{PREFIX}DATABASE_URL",
            f"postgresql://{found.role}@{found.host}:{found.port}/{found.database}",
        )
        monkeypatch.setenv(f"{PREFIX}DATABASE_PASSWORD_FILE", str(password))
        yield found


def _started(server: Server) -> None:
    """The state as a worker of counting leaves it: its profile, one
    message, its progress now."""
    with Store.open_server(server) as store:
        store.set_profile(
            Profile(
                agent="counting",
                instance=None,
                agent_version="1",
                package_version="0.11.1",
                stage="shadow",
                accounts=(),
                keyword="agent-counted",
                poll_seconds=60.0,
                gateway_timeout_seconds=120.0,
                model_alias="",
                prompt_version="",
                started=NOW,
            )
        )
        store.enqueue(MessageRef(account_id="acc", message_id="m1"), NOW)
        store.set_progress(NOW)


def test_before_the_first_start_there_is_no_state(
    server: Server, capsys: pytest.CaptureFixture[str]
) -> None:
    place = f"the database {server.database} on {server.host}:{server.port}"

    assert main(["health", "--agent", "counting"]) == 1
    assert capsys.readouterr().out == "counting: unhealthy, no progress yet\n"
    assert main(["report", "--agent", "counting", "--offline"]) == 2
    assert f"no state in {place}, schema {server.role} yet" in capsys.readouterr().err
    assert main(["status"]) == 0
    assert "nothing yet: no agent has started on it" in capsys.readouterr().out


def test_the_commands_read_the_state_on_the_server(
    server: Server, capsys: pytest.CaptureFixture[str]
) -> None:
    _started(server)
    place = (
        f"state: the database {server.database} on {server.host}:{server.port},"
        f" schema {server.role}"
    )

    assert main(["paths"]) == 0
    assert place in capsys.readouterr().out.splitlines()
    assert main(["health", "--agent", "counting"]) == 0
    assert capsys.readouterr().out.startswith("counting: healthy, last progress")
    assert main(["report", "--agent", "counting", "--offline"]) == 0
    assert "m1" in capsys.readouterr().out
    assert main(["status"]) == 0
    out = capsys.readouterr()
    assert place in out.out.splitlines()
    assert "  pending=1" in "\n".join(out.out.splitlines())
    assert server.password not in out.out + out.err
