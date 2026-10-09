"""Whether the service answers, the same for both clients."""

from __future__ import annotations

from collections.abc import Callable

from benethos_mailbox_client import Health

from ..fake_api import FakeApi


async def test_health(make_client: Callable) -> None:
    api = FakeApi({"status": "ok", "version": "0.3.1"})
    assert await make_client(api).health() == Health("ok", "0.3.1")
    assert api.call() == ("GET", "/health", {}, None)
