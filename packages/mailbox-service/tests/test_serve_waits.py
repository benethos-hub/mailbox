"""``serve`` on a database server waits for the database at start, a
while, and then names where it looked. The other commands do not wait,
and no line of the terminal shows the password."""

from __future__ import annotations

from pathlib import Path
from typing import NoReturn

import pytest

from benethos_mailbox_service import assembly
from benethos_mailbox_service.assembly import lifecycle
from benethos_mailbox_service.cli import main, serve
from benethos_mailbox_service.errors import StorageError

PASSWORD = "an-invented-role-password"  # pragma: allowlist secret


@pytest.fixture
def away(monkeypatch: pytest.MonkeyPatch, tmp_path: Path) -> list[float]:
    """Settings of a database server that does not answer, and a clock
    the waiting moves: the pauses it took. A refused connection takes
    seconds on some systems: the opening fails at once instead."""
    password = tmp_path / "database_password"
    password.write_text(PASSWORD, encoding="utf-8")
    monkeypatch.setenv("MAILBOX_SERVICE_STORAGE", "postgres")
    monkeypatch.setenv(
        "MAILBOX_SERVICE_DATABASE_URL", "postgresql://svc@db.example.org:5432/mailbox"
    )
    monkeypatch.setenv("MAILBOX_SERVICE_DATABASE_PASSWORD_FILE", str(password))
    monkeypatch.setenv("MAILBOX_SERVICE_DATABASE_START_WAIT", "9")
    paused: list[float] = []
    now = [0.0]

    def sleep(seconds: float) -> None:
        paused.append(seconds)
        now[0] += seconds

    def unreachable(*args: object, **kwargs: object) -> NoReturn:
        raise StorageError("the database failed: OperationalError (08001)")

    monkeypatch.setattr(assembly, "create_app", unreachable)
    monkeypatch.setattr(lifecycle, "build_services", unreachable)
    monkeypatch.setattr(serve.Waiting, "sleep", staticmethod(sleep))
    monkeypatch.setattr(serve.Waiting, "clock", staticmethod(lambda: now[0]))
    return paused


def test_serve_waits_then_names_the_host_and_the_role(
    away: list[float], capsys: pytest.CaptureFixture[str]
) -> None:
    assert main(["serve"]) == 1
    err = capsys.readouterr().err
    assert err.startswith("error: the database on db.example.org as svc could not")
    assert "within 9 seconds: the database failed: OperationalError" in err
    assert PASSWORD not in err
    assert away == [2.0, 2.0, 2.0, 2.0]


def test_another_command_does_not_wait(
    away: list[float], capsys: pytest.CaptureFixture[str]
) -> None:
    assert main(["users", "create-admin"]) == 1
    assert away == []
    assert PASSWORD not in capsys.readouterr().err


def test_a_secret_never_reaches_the_terminal(
    monkeypatch: pytest.MonkeyPatch, capsys: pytest.CaptureFixture[str]
) -> None:
    from benethos_mailbox_common.log import redact
    from benethos_mailbox_service.errors import StorageError

    def failing(args: object) -> None:
        redact.note(PASSWORD)
        raise StorageError(f"a driver that says {PASSWORD}")

    monkeypatch.setattr(serve, "run", failing)
    assert main(["serve"]) == 1
    assert PASSWORD not in capsys.readouterr().err
