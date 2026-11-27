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
from pathlib import Path
from typing import Any

from .. import __version__
from ..contract import Agent, state_name
from ..errors import ConfigError
from ..llm.gateway import Gateway
from ..logbook import process, record
from ..records import Profile
from ..runtime.loop import Worker
from ..runtime.model import NoModel
from ..runtime.readiness import start
from ..settings import PREFIX, Settings
from ..sources.mailbox import Mailbox, connect
from ..store import Store, earlier_file, path_for
from ..telemetry.otlp import open_spans

__all__ = [
    "TRANSPORTS",
    "Session",
    "former_file",
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
        self,
        agent: Agent,
        store: Store,
        mailbox: Mailbox,
        gateway: Gateway | NoModel,
        worker: Worker,
    ) -> None:
        self.agent = agent
        self.store = store
        self.mailbox = mailbox
        self.gateway = gateway
        self.worker = worker


def former_file(data_dir: Path, cls: type[Agent], instance: str | None) -> Path | None:
    """The state file of the agent under a former name of it, when there
    is one and none under its name: a writer does not start anew beside
    it, as the cursor and every decision are in it."""
    if path_for(data_dir, state_name(cls.name, instance)).is_file():
        return None
    for name in cls.former_names:
        found = path_for(data_dir, state_name(name, instance))
        if found.is_file():
            return found
    return None


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
    """The mailbox service, and the gateway for an agent that asks a model,
    as it is configured."""
    async with AsyncExitStack() as stack:
        mailbox = await stack.enter_async_context(mailbox_for(settings))
        gateway: Gateway | NoModel = NoModel()
        if agent.asks_model():
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


def _store_of(agent: Agent, settings: Settings) -> Store:
    """The state the agent writes: in a database of its own on a server
    for storage postgres, else in its state file, which does not start
    anew beside one at the place before or under a former name."""
    if settings.storage == "postgres":
        return Store.open_server(
            settings.database_server(),
            readers=tuple(settings.database_readers),
            setting=f"{PREFIX}DATABASE_READERS",
        )
    path = path_for(settings.data_dir, agent.state_name)
    earlier = earlier_file(settings.data_dir, agent.state_name)
    if earlier is not None:
        raise ConfigError(
            f"the state file of {agent.label} lies at {earlier.resolve()}, "
            f"the agents keep it at {path.resolve()} now: move it there, "
            f"or set {PREFIX}DATA_DIR to its folder"
        )
    former = former_file(settings.data_dir, type(agent), settings.instance)
    if former is not None:
        raise ConfigError(
            f"the state file of {agent.label} lies at {former.resolve()}, "
            f"under a former name of the agent: rename it to {path.resolve()}"
        )
    return Store.open(path)


@asynccontextmanager
async def session(cls: type[Agent], settings: Settings) -> AsyncIterator[Session]:
    agent = start(cls, settings)
    async with AsyncExitStack() as stack:
        mailbox, gateway = await stack.enter_async_context(upstreams(agent, settings))
        store = stack.enter_context(_store_of(agent, settings))
        if store.rights is not None:
            record(
                process.DatabaseClosed(
                    agent=agent.label,
                    owner=store.rights.owner,
                    readers=len(store.rights.readers),
                    revoked=len(store.rights.revoked),
                )
            )
        if store.migrated is not None:
            found = store.migrated
            record(
                process.Migrated(
                    agent=agent.label,
                    before=found.before,
                    after=found.after,
                    notes=found.notes,
                )
            )
        # For a reader from outside, which holds none of these settings.
        store.set_profile(
            Profile(
                agent=agent.name,
                instance=agent.instance,
                agent_version=agent.version,
                package_version=__version__,
                stage=settings.stage,
                accounts=tuple(settings.accounts),
                keyword=agent.keyword,
                poll_seconds=settings.poll_seconds,
                gateway_timeout_seconds=settings.gateway_timeout_seconds,
                model_alias=gateway.model,
                prompt_version=agent.prompt_version,
                started=now(),
            )
        )
        spans = stack.enter_context(open_spans(settings, agent.name))
        worker = Worker(
            agent=agent,
            store=store,
            mailbox=mailbox,
            gateway=gateway,
            now=now,
            spans=spans,
        )
        yield Session(agent, store, mailbox, gateway, worker)
