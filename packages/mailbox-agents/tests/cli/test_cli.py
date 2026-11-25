"""The command line."""

from __future__ import annotations

import asyncio
import os
import sqlite3
import stat
import sys
from importlib.metadata import version
from pathlib import Path

import httpx
import pytest

from benethos_mailbox_agents import __version__
from benethos_mailbox_agents.cli import PROG, main, session
from benethos_mailbox_agents.runtime.loop import Worker
from benethos_mailbox_agents.settings import DATA_DIR, PREFIX

from ..agents_fake import FakeGateway, FakeService, wire_message
from ..agents_helpers import configure


def test_version_is_the_distributions() -> None:
    assert __version__ == version("benethos-mailbox-agents")


def test_version_flag_prints_name_and_version(
    capsys: pytest.CaptureFixture[str],
) -> None:
    with pytest.raises(SystemExit) as raised:
        main(["--version"])

    assert raised.value.code == 0
    assert capsys.readouterr().out.strip() == f"{PROG} {__version__}"


def test_no_command_prints_the_help(capsys: pytest.CaptureFixture[str]) -> None:
    assert main([]) == 0
    assert capsys.readouterr().out.startswith(f"usage: {PROG}")


def test_status_names_what_is_missing(
    service: FakeService, capsys: pytest.CaptureFixture[str]
) -> None:
    assert main(["status"]) == 0

    out = capsys.readouterr().out
    assert "counting 1: misses MAILBOX_AGENTS_SERVICE_URL" in out


def test_status_warns_of_a_keyword_set_for_every_agent(
    service: FakeService,
    monkeypatch: pytest.MonkeyPatch,
    capsys: pytest.CaptureFixture[str],
) -> None:
    monkeypatch.setenv(f"{PREFIX}KEYWORD", "agent-bills")

    assert main(["status"]) == 0

    first = capsys.readouterr().out.splitlines()[0]
    assert first == (
        "MAILBOX_AGENTS_KEYWORD is set for every agent of these settings: "
        "give each agent its own env file"
    )


def test_status_without_a_keyword_set_warns_of_none(
    service: FakeService, capsys: pytest.CaptureFixture[str]
) -> None:
    assert main(["status"]) == 0

    assert "MAILBOX_AGENTS_KEYWORD" not in capsys.readouterr().out


@pytest.mark.skipif(sys.platform == "win32", reason="Windows keeps no Unix rights")
def test_the_state_file_is_for_its_owner_only(
    service: FakeService, monkeypatch: pytest.MonkeyPatch, tmp_path: Path
) -> None:
    configure(monkeypatch)
    monkeypatch.setenv(f"{PREFIX}DATA_DIR", str(tmp_path / "data"))
    previous = os.umask(0o022)
    try:
        assert main(["run", "--agent", "counting"]) == 0
    finally:
        os.umask(previous)

    assert stat.S_IMODE((tmp_path / "data" / "counting.db").stat().st_mode) == 0o600


def test_run_and_status_with_a_state_file(
    service: FakeService,
    monkeypatch: pytest.MonkeyPatch,
    capsys: pytest.CaptureFixture[str],
) -> None:
    configure(monkeypatch)

    assert main(["run", "--agent", "counting"]) == 0
    assert "counting made its state file at schema" in capsys.readouterr().err
    service.add(wire_message("m1"))
    service.add(wire_message("m2"))
    assert main(["run", "--agent", "counting"]) == 0
    assert "done=2" in capsys.readouterr().out

    assert main(["status"]) == 0
    out = capsys.readouterr().out
    assert "counting 1: ready" in out
    assert "done=2" in out
    assert "last progress: 20" in out


def test_a_broken_state_file_is_named_and_the_others_still_listed(
    service: FakeService,
    monkeypatch: pytest.MonkeyPatch,
    capsys: pytest.CaptureFixture[str],
) -> None:
    configure(monkeypatch)
    assert main(["run", "--agent", "counting"]) == 0
    capsys.readouterr()
    (DATA_DIR / "awaiting_reply.db").write_text("no database " * 100)

    assert main(["status"]) == 0
    out = capsys.readouterr().out
    assert "state file unreadable: the state file awaiting_reply.db" in out
    starts = [line.split(" ")[0] for line in out.splitlines()]
    for name in (
        "awaiting_reply",
        "counting",
        "inquiries",
        "invoices",
        "categorization",
    ):
        assert name in starts
    assert "last progress: 20" in out

    assert main(["health", "--agent", "awaiting_reply"]) == 1
    captured = capsys.readouterr()
    assert captured.out.startswith("awaiting_reply: unhealthy, the state file")
    assert "Traceback" not in captured.err


def test_a_data_folder_that_is_a_file_ends_run_in_one_line(
    service: FakeService,
    monkeypatch: pytest.MonkeyPatch,
    capsys: pytest.CaptureFixture[str],
) -> None:
    configure(monkeypatch)
    DATA_DIR.parent.mkdir()
    DATA_DIR.write_text("not a folder", encoding="utf-8")

    assert main(["run", "--agent", "counting"]) == 1

    err = capsys.readouterr().err
    assert err.splitlines() == [
        f"{PROG}: the state file counting.db: its folder or lock cannot be made "
        "(FileExistsError)"
    ]


def test_a_state_file_of_a_newer_schema_is_named_and_unhealthy(
    service: FakeService,
    monkeypatch: pytest.MonkeyPatch,
    capsys: pytest.CaptureFixture[str],
) -> None:
    configure(monkeypatch)
    assert main(["run", "--agent", "counting"]) == 0
    capsys.readouterr()
    with sqlite3.connect(DATA_DIR / "counting.db") as db:
        db.execute("PRAGMA user_version = 99")
    db.close()

    assert main(["status"]) == 0
    out = capsys.readouterr().out
    assert "state file unreadable: the state file is at schema version 99" in out
    starts = [line.split(" ")[0] for line in out.splitlines()]
    for name in (
        "awaiting_reply",
        "counting",
        "inquiries",
        "invoices",
        "categorization",
    ):
        assert name in starts

    assert main(["health", "--agent", "counting"]) == 1
    captured = capsys.readouterr()
    assert captured.out.startswith("counting: unhealthy, the state file is at")
    assert captured.err == ""


def test_backfill_takes_recent_messages_up(
    service: FakeService,
    monkeypatch: pytest.MonkeyPatch,
    capsys: pytest.CaptureFixture[str],
) -> None:
    configure(monkeypatch)
    service.add(wire_message("m1"), change=None)

    assert main(["backfill", "--agent", "counting", "--days", "3"]) == 0

    assert "1 taken up" in capsys.readouterr().out
    assert service.requests[0].url.params["after"]


def test_backfill_stops_when_the_gateway_is_away(
    service: FakeService,
    monkeypatch: pytest.MonkeyPatch,
    capsys: pytest.CaptureFixture[str],
) -> None:
    configure(monkeypatch)
    monkeypatch.setenv(f"{PREFIX}GATEWAY_URL", "https://gateway.example.test/v1")
    monkeypatch.setenv(f"{PREFIX}GATEWAY_KEY", "gateway-key")
    monkeypatch.setenv(f"{PREFIX}MODEL", "alias")
    gateway = FakeGateway()

    def away(request: httpx.Request) -> httpx.Response:
        # A backfill that asks again and again must fail, not hang the suite.
        assert len(gateway.requests) < 3, "the gateway was asked again"
        return gateway.handle(request)

    monkeypatch.setitem(session.TRANSPORTS, "gateway", httpx.MockTransport(away))
    service.add(wire_message("m1", subject="Your invoice"), change=None)

    assert main(["backfill", "--agent", "invoices", "--days", "3"]) == 1

    assert len(gateway.requests) == 1
    assert "taken up" not in capsys.readouterr().out


def test_a_negative_backfill_is_refused(
    service: FakeService, monkeypatch: pytest.MonkeyPatch
) -> None:
    configure(monkeypatch)

    assert main(["backfill", "--agent", "counting", "--days", "-1"]) == 2


def test_worker_runs_until_stopped(
    service: FakeService, monkeypatch: pytest.MonkeyPatch, tmp_path: Path
) -> None:
    configure(monkeypatch)

    async def one_pass(self: Worker, stop: asyncio.Event) -> None:
        await self.run_pass()

    monkeypatch.setattr(Worker, "run", one_pass)

    assert main(["worker", "--agent", "counting"]) == 0
    assert (tmp_path / DATA_DIR / "counting.db").is_file()


def test_a_state_file_at_the_place_before_is_not_left_behind(
    service: FakeService,
    monkeypatch: pytest.MonkeyPatch,
    capsys: pytest.CaptureFixture[str],
) -> None:
    """Before, the state files lay in data/ below the working directory. A
    writer does not start a new one beside such a file, and paths and
    status name it."""
    configure(monkeypatch)
    Path("data").mkdir()
    Path("data", "counting.db").write_bytes(b"")

    assert main(["run", "--agent", "counting"]) == 2
    err = capsys.readouterr().err
    assert "the state file of counting lies at" in err
    assert f"set {PREFIX}DATA_DIR to its folder" in err
    assert not (DATA_DIR / "counting.db").exists()

    assert main(["paths"]) == 0
    assert "a state file lies at" in capsys.readouterr().out
    assert main(["status"]) == 0
    assert "move it to" in capsys.readouterr().out


def test_paths(
    service: FakeService, capsys: pytest.CaptureFixture[str], tmp_path: Path
) -> None:
    assert main(["paths"]) == 0

    out = capsys.readouterr().out
    assert "settings:" in out and "(missing)" in out
    assert "counting:" in out and "none yet" in out


@pytest.mark.parametrize(
    ("argv", "code", "said"),
    [
        (["run", "--agent", "nobody"], 2, "no agent 'nobody'"),
        (["run", "--agent", "counting"], 2, "misses settings"),
        (["--env-file", "missing.env", "status"], 2, "does not exist"),
    ],
)
def test_a_configuration_to_correct_is_a_2(
    service: FakeService,
    capsys: pytest.CaptureFixture[str],
    argv: list[str],
    code: int,
    said: str,
) -> None:
    assert main(argv) == code
    assert said in capsys.readouterr().err


def test_a_service_away_during_the_pass_is_a_1(
    service: FakeService, monkeypatch: pytest.MonkeyPatch
) -> None:
    configure(monkeypatch)
    monkeypatch.setenv(f"{PREFIX}POLL_SECONDS", "60")
    monkeypatch.setenv(f"{PREFIX}BACKOFF_CEILING_SECONDS", "10")
    assert main(["run", "--agent", "counting"]) == 0
    service.add(wire_message("m1"))

    def fetch_away(request: httpx.Request) -> httpx.Response:
        if request.method == "GET" and "/messages/" in request.url.path:
            return httpx.Response(503, json={"error": "unavailable"})
        return service.handle(request)

    monkeypatch.setitem(session.TRANSPORTS, "service", httpx.MockTransport(fetch_away))

    assert main(["run", "--agent", "counting"]) == 1


def test_a_service_that_is_away_is_a_1(
    service: FakeService,
    monkeypatch: pytest.MonkeyPatch,
    capsys: pytest.CaptureFixture[str],
) -> None:
    configure(monkeypatch)
    service.down = True

    assert main(["run", "--agent", "counting"]) == 1
    assert "mailbox service" in capsys.readouterr().err


def test_the_error_line_writes_a_control_character_escaped(
    service: FakeService,
    monkeypatch: pytest.MonkeyPatch,
    capsys: pytest.CaptureFixture[str],
) -> None:
    configure(monkeypatch)
    code = "".join(map(chr, (0x1B, 0x5D, 0x30, 0x3B, 0x6F, 0x07, 0x1B))) + "[2J"

    def refuse(request: httpx.Request) -> httpx.Response:
        if request.url.path != "/health":
            return httpx.Response(
                403, json={"error": {"code": code, "message": "refused"}}
            )
        return service.handle(request)

    monkeypatch.setitem(session.TRANSPORTS, "service", httpx.MockTransport(refuse))

    assert main(["run", "--agent", "counting"]) != 0
    err = capsys.readouterr().err
    assert err.splitlines()[-1].startswith(f"{PROG}: the mailbox service refused")
    assert chr(0x1B) not in err
    assert chr(0x07) not in err
