"""The life of the services: for one command on the host, and while the
app serves, with the background work beside it."""

from __future__ import annotations

from collections.abc import AsyncIterator, Awaitable, Callable, Iterator
from contextlib import ExitStack, asynccontextmanager, contextmanager
from pathlib import Path

import anyio

from ..config import Settings
from ..domain.activity import DISPATCHER, SERVICE, WORKER, ActivityLog, Actor
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
    services: Services, settings: Settings, settings_file: Path | None
) -> AsyncIterator[None]:
    """While the app serves: the database held, the start and the end in
    the log, the background work running."""
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
            async with _running(services):
                yield
        finally:
            services.activity.record(said.ServiceStopped(by=SERVICE))


def _purge(services: Services) -> None:
    """The records older than the days to keep, removed when the service
    starts. Else they wait for the first new record of their kind."""
    for purge in services.purges:
        purge()


@asynccontextmanager
async def _running(services: Services) -> AsyncIterator[None]:
    """The background work while the app serves, then every connection
    closed."""
    async with anyio.create_task_group() as background:
        if services.worker is not None:
            background.start_soon(_loop, services.activity, WORKER, services.worker.run)
        background.start_soon(
            _loop, services.activity, DISPATCHER, services.deliveries.run
        )
        try:
            yield
        finally:
            # The worker first, so it opens nothing new while the
            # adapters close.
            background.cancel_scope.cancel()
    await services.aclose()


async def _loop(
    activity: ActivityLog, by: Actor, run: Callable[[], Awaitable[None]]
) -> None:
    """A background loop, which runs until the service stops. Should it
    end otherwise, the log says so."""
    try:
        await run()
    except Exception as exc:
        activity.record(said.LoopEnded(by=by, error=exc))
        raise
