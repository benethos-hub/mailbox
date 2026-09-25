"""Fixtures for the MCP package. Offline: the REST API is an httpx mock."""

from __future__ import annotations

import os
from collections.abc import Callable

import httpx
import pytest

from benethos_mailbox_mcp import server
from benethos_mailbox_mcp.client import MailboxApiClient

Handler = Callable[[httpx.Request], httpx.Response]


@pytest.fixture(autouse=True)
def no_configuration_from_this_machine(monkeypatch: pytest.MonkeyPatch) -> None:
    for name in list(os.environ):
        if name.startswith("MAILBOX_SERVICE_"):
            monkeypatch.delenv(name)


@pytest.fixture
def make_client(
    monkeypatch: pytest.MonkeyPatch,
) -> Callable[[Handler], MailboxApiClient]:
    """Build a client answered by ``handler`` and install it for the tools."""

    def make(handler: Handler) -> MailboxApiClient:
        client = MailboxApiClient(
            base_url="http://mail.test",
            token="secret",
            transport=httpx.MockTransport(handler),
        )
        monkeypatch.setattr(server, "_client", client)
        return client

    return make
