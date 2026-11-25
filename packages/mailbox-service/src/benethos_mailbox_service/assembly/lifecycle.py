"""The life of the services: for one command on the host, and while the
app serves, with the background work beside it."""

from __future__ import annotations

from collections.abc import AsyncIterator, Awaitable, Callable, Iterator
from contextlib import ExitStack, asynccontextmanager, contextmanager
from pathlib import Path

import anyio

from ..config import Settings
from ..domain.activity import (
    DISPATCHER,
    OUTBOX,
    SERVICE,
    WORKER,
    ActivityLog,
    Actor,
)
from ..domain.activity import system as said
from .domain import build_services
from .services import Services


@contextmanager
def opened(settings: Settings) -> Iterator[Services]:
    """The services for one command on the host, closed afterwards."""
    services = build_services(settings)
    try:
        yield services
    finally:
        services.close()


@asynccontextmanager
async def serving(
    services: Services,
    settings: Settings,
    settings_file: Path | None,
    stop: Callable[[], None] | None = None,
) -> AsyncIterator[None]:
    """While the app serves: the database held, the start and the end in
    the log, the background work running. Should a background loop end,
    ``stop`` ends the server, and the service stops as it would at a
    signal. Without ``stop`` the loop's error ends the background work."""
    with ExitStack() as held:
        store = services.store
        if store is not None and not held.enter_context(store.serving()):
            services.activity.record(said.DatabaseShared(by=SERVICE))
        services.activity.record(
            said.ServiceStarted(
                by=SERVICE,
                settings=str(settings_file) if settings_file else None,
                database=str(settings.database_path) if store else None,
                schema=store.schema_version() if store else None,
            )
        )
        _purge(services)
        try:
            async with _running(services, stop):
                yield
        finally:
            services.activity.record(said.ServiceStopped(by=SERVICE))


def _purge(services: Services) -> None:
    """The records older than the days to keep, removed when the service
    starts. Else they wait for the first new record of their kind."""
    for purge in services.purges:
        purge()


@asynccontextmanager
async def _running(
    services: Services, stop: Callable[[], None] | None
) -> AsyncIterator[None]:
    """The background work while the app serves, then every connection
    closed, also when a loop ended with an error."""
    activity = services.activity
    try:
        async with anyio.create_task_group() as background:
            if services.worker is not None:
                background.start_soon(
                    _loop, activity, WORKER, services.worker.run, stop
                )
            background.start_soon(
                _loop, activity, DISPATCHER, services.deliveries.run, stop
            )
            if services.outbox is not None:
                background.start_soon(
                    _loop, activity, OUTBOX, services.outbox.run, stop
                )
            try:
                yield
            finally:
                # The worker first, so it opens nothing new while the
                # adapters close.
                background.cancel_scope.cancel()
    finally:
        await services.aclose()


async def _loop(
    activity: ActivityLog,
    by: Actor,
    run: Callable[[], Awaitable[None]],
    stop: Callable[[], None] | None,
) -> None:
    """A background loop, which runs until the service stops. Should it
    end otherwise, the log says so and ``stop`` ends the server: a
    service that no longer syncs or delivers should not go on answering
    as if it did. A switched off worker is no loop at all."""
    try:
        await run()
    except Exception as exc:
        activity.record(said.LoopEnded(by=by, error=exc))
        if stop is None:
            raise
        stop()
