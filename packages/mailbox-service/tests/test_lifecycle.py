"""The life of the services while the app serves: a background loop that
ends stops the server, and every connection closes either way."""

from __future__ import annotations

import logging

import anyio
import pytest

from benethos_mailbox_service.assembly import Services
from benethos_mailbox_service.assembly.lifecycle import serving
from benethos_mailbox_service.config import Settings


def broken_dispatcher(services: Services, monkeypatch: pytest.MonkeyPatch) -> None:
    async def run() -> None:
        raise RuntimeError("Ladybird broke")

    monkeypatch.setattr(services.deliveries, "run", run)


def counted_close(services: Services, monkeypatch: pytest.MonkeyPatch) -> list[bool]:
    closed: list[bool] = []
    real = services.adapters.close

    async def close() -> None:
        closed.append(True)
        await real()

    monkeypatch.setattr(services.adapters, "close", close)
    return closed


async def test_a_loop_that_ends_stops_the_server_once(
    services: Services,
    settings: Settings,
    monkeypatch: pytest.MonkeyPatch,
    caplog: pytest.LogCaptureFixture,
) -> None:
    broken_dispatcher(services, monkeypatch)
    closed = counted_close(services, monkeypatch)
    stops: list[bool] = []
    stopped = anyio.Event()

    def stop() -> None:
        stops.append(True)
        stopped.set()

    with caplog.at_level(logging.ERROR), anyio.fail_after(5):
        async with serving(services, settings, None, stop):
            await stopped.wait()
    assert stops == [True] and closed == [True]
    assert any(r.name.endswith("loop_ended") for r in caplog.records)


async def test_without_a_stop_the_error_goes_on_and_all_closes(
    services: Services, settings: Settings, monkeypatch: pytest.MonkeyPatch
) -> None:
    broken_dispatcher(services, monkeypatch)
    closed = counted_close(services, monkeypatch)
    with anyio.fail_after(5), pytest.raises(ExceptionGroup):
        async with serving(services, settings, None):
            await anyio.sleep(5)
    assert closed == [True]
