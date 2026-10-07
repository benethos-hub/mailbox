"""Fixtures for the client package. Offline: the REST API is an httpx
mock. Most tests run twice, once for each client, through ``Either``."""

from __future__ import annotations

import inspect
from collections.abc import AsyncIterator, Callable
from typing import Any

import httpx
import pytest

from benethos_mailbox_client import MailboxClient, SyncMailboxClient
from benethos_mailbox_client.wire import ALLOW_HTTP_ENV, TOKEN_ENV, URL_ENV

Handler = Callable[[httpx.Request], httpx.Response]


@pytest.fixture(autouse=True)
def no_settings_from_this_machine(monkeypatch: pytest.MonkeyPatch) -> None:
    for name in (URL_ENV, TOKEN_ENV, ALLOW_HTTP_ENV):
        monkeypatch.delenv(name, raising=False)


class Either:
    """A client of either kind, awaited alike: each method of the sync
    client answers through a coroutine here, so one test covers both."""

    def __init__(self, client: MailboxClient | SyncMailboxClient) -> None:
        self.client = client

    def __getattr__(self, name: str) -> Callable[..., Any]:
        method = getattr(self.client, name)

        async def call(*args: Any, **kwargs: Any) -> Any:
            found = method(*args, **kwargs)
            return await found if inspect.isawaitable(found) else found

        return call

    async def close(self) -> None:
        if isinstance(self.client, MailboxClient):
            await self.client.aclose()
        else:
            self.client.close()


@pytest.fixture(params=["async", "sync"])
async def make_client(
    request: pytest.FixtureRequest,
) -> AsyncIterator[Callable[..., Either]]:
    """Build a client of the parameter's kind, answered by ``handler``."""
    made: list[Either] = []

    def make(handler: Handler, **settings: Any) -> Either:
        settings = {"base_url": "https://mail.test", "token": "secret", **settings}
        transport = httpx.MockTransport(handler)
        either = Either(
            MailboxClient(transport=transport, **settings)
            if request.param == "async"
            else SyncMailboxClient(transport=transport, **settings)
        )
        made.append(either)
        return either

    yield make
    for either in made:
        await either.close()
