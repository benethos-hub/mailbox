"""The pieces of one agent's process, wired: the mailbox, the gateway, the
state file and the worker over them."""

from __future__ import annotations

from collections.abc import AsyncIterator
from contextlib import (
    AbstractAsyncContextManager,
    AsyncExitStack,
    asynccontextmanager,
)
from datetime import UTC, datetime
from typing import Any

from ..contract import Agent
from ..llm.gateway import Gateway
from ..logbook import process, record
from ..runtime.loop import Worker
from ..runtime.model import NoModel
from ..runtime.readiness import start, uses_model
from ..settings import Settings
from ..sources.mailbox import Mailbox, connect
from ..store import Store, path_for

__all__ = [
    "TRANSPORTS",
    "Session",
    "now",
    "session",
    "upstreams",
]

# Transports for the two upstreams, by "service" and "gateway". Empty in a
# real process. A test puts its mocks here.
TRANSPORTS: dict[str, Any] = {}


def now() -> datetime:
    return datetime.now(UTC)


class Session:
    """What one command works with."""

    def __init__(
        self, agent: Agent, store: Store, mailbox: Mailbox, worker: Worker
    ) -> None:
        self.agent = agent
        self.store = store
        self.mailbox = mailbox
        self.worker = worker


def mailbox_for(settings: Settings) -> AbstractAsyncContextManager[Mailbox]:
    """The mailbox service as the settings name it."""
    return connect(
        settings.service_url or "",
        settings.secret("service_token"),
        allow_http=settings.service_allow_http,
        verify=settings.ssl_context(),
        transport=TRANSPORTS.get("service"),
    )


@asynccontextmanager
async def upstreams(
    agent: Agent, settings: Settings
) -> AsyncIterator[tuple[Mailbox, Gateway | NoModel]]:
    """The mailbox service, and the gateway for an agent that asks a model."""
    async with AsyncExitStack() as stack:
        mailbox = await stack.enter_async_context(mailbox_for(settings))
        gateway: Gateway | NoModel = NoModel()
        if uses_model(type(agent)):
            gateway = await stack.enter_async_context(
                Gateway(
                    settings.gateway_url or "",
                    settings.secret("gateway_key"),
                    settings.model or "",
                    timeout=settings.gateway_timeout_seconds,
                    allow_http=settings.gateway_allow_http,
                    verify=settings.ssl_context(),
                    transport=TRANSPORTS.get("gateway"),
                )
            )
        yield mailbox, gateway


@asynccontextmanager
async def session(cls: type[Agent], settings: Settings) -> AsyncIterator[Session]:
    agent = start(cls, settings)
    async with AsyncExitStack() as stack:
        mailbox, gateway = await stack.enter_async_context(upstreams(agent, settings))
        store = stack.enter_context(Store.open(path_for(settings.data_dir, agent.name)))
        if store.migrated is not None:
            found = store.migrated
            record(
                process.Migrated(
                    agent=agent.name,
                    before=found.before,
                    after=found.after,
                    notes=found.notes,
                )
            )
        worker = Worker(
            agent=agent, store=store, mailbox=mailbox, gateway=gateway, now=now
        )
        yield Session(agent, store, mailbox, worker)
