"""The command cockpit: only with its secret, on its port."""

from __future__ import annotations

import asyncio
import contextlib
import logging
import socket
import sys
from pathlib import Path

import httpx
import pytest

from benethos_mailbox_agents.cli import build_parser, main
from benethos_mailbox_agents.cockpit.app import Cockpit, make_app
from benethos_mailbox_agents.cockpit.server import serve
from benethos_mailbox_agents.settings import PREFIX

from ..clocks import Clock

SECRET = "cockpit-secret-value"  # pragma: allowlist secret


def test_the_command_is_in_the_parser() -> None:
    assert build_parser().parse_args(["cockpit"]).command == "cockpit"


def test_without_its_secret_the_cockpit_does_not_start(
    capsys: pytest.CaptureFixture[str],
) -> None:
    assert main(["cockpit"]) == 2

    assert f"{PREFIX}COCKPIT_SECRET is not set" in capsys.readouterr().err


def test_a_port_taken_is_a_configuration_to_correct(
    monkeypatch: pytest.MonkeyPatch,
    capsys: pytest.CaptureFixture[str],
    tmp_path: Path,
) -> None:
    monkeypatch.setenv(f"{PREFIX}COCKPIT_SECRET", SECRET)
    monkeypatch.setenv(f"{PREFIX}DATA_DIR", str(tmp_path))
    with socket.socket() as taken:
        if sys.platform == "win32":
            taken.setsockopt(socket.SOL_SOCKET, socket.SO_EXCLUSIVEADDRUSE, 1)
        taken.bind(("127.0.0.1", 0))
        taken.listen()
        port: int = taken.getsockname()[1]
        monkeypatch.setenv(f"{PREFIX}COCKPIT_PORT", str(port))

        assert main(["cockpit"]) == 2

    err = capsys.readouterr().err
    assert f"cannot be served on port {port}: correct {PREFIX}COCKPIT_PORT" in err
    assert SECRET not in err


def _free_port() -> int:
    with socket.socket() as probe:
        probe.bind(("127.0.0.1", 0))
        port: int = probe.getsockname()[1]
        return port


async def test_the_cockpit_serves_its_pages_and_says_so(
    tmp_path: Path, caplog: pytest.LogCaptureFixture
) -> None:
    caplog.set_level(logging.INFO)
    port = _free_port()
    app = make_app(Cockpit(tmp_path, SECRET, None, Clock()))
    task = asyncio.create_task(serve(app, "127.0.0.1", port, named=False))
    try:
        async with httpx.AsyncClient() as client:
            for _ in range(250):
                with contextlib.suppress(httpx.ConnectError):
                    answer = await client.get(f"http://127.0.0.1:{port}/login")
                    break
                await asyncio.sleep(0.02)
        assert answer.status_code == 200
        assert "Sign in to the cockpit" in answer.text
    finally:
        task.cancel()
        with contextlib.suppress(asyncio.CancelledError):
            await task

    assert f"cockpit began serving its pages on port {port}: ids only" in caplog.text
    assert SECRET not in caplog.text
