"""The life of the services while the app serves: a background loop that
ends stops the server, and every connection closes either way."""

from __future__ import annotations

import logging
from collections.abc import Callable
from contextlib import AbstractContextManager, nullcontext
from dataclasses import replace

import anyio
import pytest

from benethos_mailbox_service.assembly import Services
from benethos_mailbox_service.assembly.lifecycle import serving
from benethos_mailbox_service.config import Settings
from benethos_mailbox_service.data.storage import Availability


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
    stops: list[str] = []
    stopped = anyio.Event()

    def stop(reason: str) -> None:
        stops.append(reason)
        stopped.set()

    with caplog.at_level(logging.ERROR), anyio.fail_after(5):
        async with serving(services, settings, None, stop):
            await stopped.wait()
    assert stops == ["a background loop ended, the service stopped"]
    assert closed == [True]
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


class _Taken:
    """A store whose lock another service takes while it is away."""

    def __init__(self) -> None:
        self.reports: list[Callable[[Availability], None]] = []

    def serving(self) -> AbstractContextManager[bool]:
        return nullcontext(True)

    def schema_version(self) -> int:
        return 26

    def watch(self, report: Callable[[Availability], None]) -> None:
        self.reports.append(report)

    def close(self) -> None:
        return None


async def test_a_lock_taken_meanwhile_stops_the_server(
    services: Services, settings: Settings, caplog: pytest.LogCaptureFixture
) -> None:
    store = _Taken()
    held = replace(services, repositories=replace(services.repositories, store=store))
    stops: list[str] = []
    with caplog.at_level(logging.ERROR), anyio.fail_after(5):
        async with serving(held, settings, None, stops.append):
            for report in store.reports:
                report(Availability(away=False, seconds=3.0, lock_lost=True))
    assert stops == ["another service took this database while it was away"]
    [line] = [r for r in caplog.records if r.name.endswith("db_taken")]
    assert line.levelno == logging.ERROR
    assert "another service" in line.getMessage()
