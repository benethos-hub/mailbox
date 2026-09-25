"""Fixtures for the MCP package. Offline: the REST API is an httpx mock."""

from __future__ import annotations

import json
import os
from collections.abc import Callable, Iterator
from typing import Any, NamedTuple

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


@pytest.fixture(autouse=True)
def no_client_left_behind() -> Iterator[None]:
    yield
    server.use_client(None)


@pytest.fixture
def make_client() -> Callable[[Handler], MailboxApiClient]:
    """Build a client answered by ``handler`` and install it for the tools."""

    def make(handler: Handler) -> MailboxApiClient:
        client = MailboxApiClient(
            base_url="http://mail.test",
            token="secret",
            transport=httpx.MockTransport(handler),
        )
        server.use_client(client)
        return client

    return make


class Call(NamedTuple):
    """One request the tools made: compares with a plain tuple."""

    method: str
    path: str
    params: dict[str, str]
    body: Any


NOTHING = object()


class FakeApi:
    """The REST API behind the tools. Each path in ``routes`` answers with
    its body. Every other request gets ``answer`` with ``status``, ``None``
    as 204, and 404 when no answer was given. Records every call, and the
    Idempotency-Key of each in ``keys``."""

    def __init__(
        self,
        answer: Any = NOTHING,
        status: int = 200,
        routes: dict[str, Any] | None = None,
    ) -> None:
        self.answer, self.status, self.routes = answer, status, routes or {}
        self.calls: list[Call] = []
        self.keys: list[str | None] = []

    def __call__(self, request: httpx.Request) -> httpx.Response:
        body = json.loads(request.content) if request.content else None
        self.calls.append(
            Call(request.method, request.url.path, dict(request.url.params), body)
        )
        self.keys.append(request.headers.get("idempotency-key"))
        if request.url.path in self.routes:
            return httpx.Response(200, json=self.routes[request.url.path])
        if self.answer is NOTHING:
            return httpx.Response(
                404, json={"error": {"code": "not_found", "message": "no route"}}
            )
        if self.answer is None:
            return httpx.Response(204)
        return httpx.Response(self.status, json=self.answer)

    def posted(self) -> list[tuple[str, Any]]:
        """Path and body of each POST."""
        return [(c.path, c.body) for c in self.calls if c.method == "POST"]


@pytest.fixture
def api(
    make_client: Callable[[Handler], MailboxApiClient],
) -> Callable[..., FakeApi]:
    """A FakeApi installed for the tools, with FakeApi's arguments."""

    def install(
        answer: Any = NOTHING, status: int = 200, routes: dict[str, Any] | None = None
    ) -> FakeApi:
        fake = FakeApi(answer, status, routes)
        make_client(fake)
        return fake

    return install
