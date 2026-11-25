"""The entrance for peers over A2A in the process of the worker: served
on its port while the worker runs, only with a token."""

from __future__ import annotations

import asyncio
import socket
import sys

import httpx
import pytest

from benethos_mailbox_agents.cli import main
from benethos_mailbox_agents.runtime.loop import Worker
from benethos_mailbox_agents.settings import PREFIX

from ..agents_fake import FakeService
from ..agents_helpers import configure

TOKEN = "peer-token-value"  # pragma: allowlist secret


def _free_port() -> int:
    with socket.socket() as probe:
        probe.bind(("127.0.0.1", 0))
        port: int = probe.getsockname()[1]
        return port


def test_the_worker_serves_peers_on_the_port_while_it_runs(
    service: FakeService, monkeypatch: pytest.MonkeyPatch
) -> None:
    configure(monkeypatch)
    port = _free_port()
    monkeypatch.setenv(f"{PREFIX}A2A_PORT", str(port))
    monkeypatch.setenv(f"{PREFIX}A2A_TOKEN", TOKEN)
    seen: dict[str, object] = {}

    async def ask_while_running(self: Worker, stop: asyncio.Event) -> None:
        url = f"http://127.0.0.1:{port}/.well-known/agent-card.json"
        async with httpx.AsyncClient() as peer:
            for _ in range(100):
                try:
                    refused = await peer.get(url)
                    break
                except httpx.ConnectError:
                    await asyncio.sleep(0.05)
            card = await peer.get(url, headers={"Authorization": f"Bearer {TOKEN}"})
        seen["refused"] = refused.status_code
        seen["card"] = card.json()

    monkeypatch.setattr(Worker, "run", ask_while_running)

    assert main(["worker", "--agent", "counting"]) == 0

    assert seen["refused"] == 401
    card = seen["card"]
    assert isinstance(card, dict) and card["name"] == "counting"
    assert card["supportedInterfaces"][0]["url"] == f"http://127.0.0.1:{port}/"
    with socket.socket() as again:
        # The entrance stopped with the worker: its port is free.
        again.bind(("127.0.0.1", port))


def test_a_port_without_a_token_is_a_configuration_to_correct(
    service: FakeService,
    monkeypatch: pytest.MonkeyPatch,
    capsys: pytest.CaptureFixture[str],
) -> None:
    configure(monkeypatch)
    monkeypatch.setenv(f"{PREFIX}A2A_PORT", str(_free_port()))

    async def not_reached(self: Worker, stop: asyncio.Event) -> None:
        raise AssertionError("the worker ran without a token for its entrance")

    monkeypatch.setattr(Worker, "run", not_reached)

    assert main(["worker", "--agent", "counting"]) == 2
    assert f"{PREFIX}A2A_TOKEN is not set" in capsys.readouterr().err


def test_a_port_taken_is_a_configuration_to_correct(
    service: FakeService,
    monkeypatch: pytest.MonkeyPatch,
    capsys: pytest.CaptureFixture[str],
) -> None:
    configure(monkeypatch)
    monkeypatch.setenv(f"{PREFIX}A2A_TOKEN", TOKEN)

    async def not_reached(self: Worker, stop: asyncio.Event) -> None:
        raise AssertionError("the worker ran without its entrance")

    monkeypatch.setattr(Worker, "run", not_reached)
    with socket.socket() as taken:
        if sys.platform == "win32":
            taken.setsockopt(socket.SOL_SOCKET, socket.SO_EXCLUSIVEADDRUSE, 1)
        taken.bind(("127.0.0.1", 0))
        taken.listen()
        port: int = taken.getsockname()[1]
        monkeypatch.setenv(f"{PREFIX}A2A_PORT", str(port))

        assert main(["worker", "--agent", "counting"]) == 2

    err = capsys.readouterr().err
    assert f"cannot be served on port {port}: correct {PREFIX}A2A_PORT" in err
