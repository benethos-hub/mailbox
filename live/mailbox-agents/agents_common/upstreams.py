"""The mailbox service and the model gateway of the settings, as the
command line connects them, and a worker over them."""

from __future__ import annotations

from contextlib import AbstractAsyncContextManager
from datetime import UTC, datetime

from benethos_mailbox_agents.contract import Agent
from benethos_mailbox_agents.llm.gateway import Gateway
from benethos_mailbox_agents.runtime.loop import Worker
from benethos_mailbox_agents.runtime.model import Asker, NoModel
from benethos_mailbox_agents.settings import Settings
from benethos_mailbox_agents.sources.mailbox import Mailbox, connect
from benethos_mailbox_agents.store import Store


def connect_mailbox(settings: Settings) -> AbstractAsyncContextManager[Mailbox]:
    """The mailbox service of the settings, as the command line connects it."""
    return connect(
        settings.service_url or "",
        settings.secret("service_token"),
        allow_http=settings.service_allow_http,
        verify=settings.ssl_context(),
    )


def open_gateway(settings: Settings) -> Gateway:
    """The model gateway of the settings, as the command line opens it."""
    return Gateway(
        settings.gateway_url or "",
        settings.secret("gateway_key"),
        settings.model or "",
        timeout=settings.gateway_timeout_seconds,
        allow_http=settings.gateway_allow_http,
        verify=settings.ssl_context(),
    )


def worker(
    agent: Agent, store: Store, mailbox: Mailbox, gateway: Asker | None = None
) -> Worker:
    """A worker of ``agent`` over the mailbox, on the clock of this machine,
    with no model unless ``gateway`` is given."""
    return Worker(
        agent=agent,
        store=store,
        mailbox=mailbox,
        gateway=gateway or NoModel(),
        now=lambda: datetime.now(UTC),
    )
