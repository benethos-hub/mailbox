"""A background loop that ends stops ``serve``, through the real server
and the command line, so a supervisor starts the service anew."""

from __future__ import annotations

import socket
import threading

import anyio
import pytest

from benethos_mailbox_service.cli import main
from benethos_mailbox_service.domain.webhooks import WebhookDispatcher

pytestmark = pytest.mark.usefixtures("master_key")


def free_port() -> int:
    with socket.socket() as probe:
        probe.bind(("127.0.0.1", 0))
        port: int = probe.getsockname()[1]
        return port


def test_serve_ends_with_an_error_when_a_loop_ends(
    monkeypatch: pytest.MonkeyPatch, capsys: pytest.CaptureFixture[str]
) -> None:
    async def broken(self: WebhookDispatcher) -> None:
        await anyio.sleep(0.5)
        raise RuntimeError("Ladybird broke")

    monkeypatch.setattr(WebhookDispatcher, "run", broken)
    codes: list[int] = []
    serving = threading.Thread(
        target=lambda: codes.append(
            main(["serve", "--host", "127.0.0.1", "--port", str(free_port())])
        ),
        daemon=True,
    )
    serving.start()
    serving.join(timeout=30)
    assert not serving.is_alive(), "serve went on after the loop ended"
    assert codes == [1]
    err = capsys.readouterr().err
    assert "error: a background loop ended, the service stopped" in err
