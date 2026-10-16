"""A real client on a server that follows its token's rights, in memory,
through the SDK's own runner. What test_listeners.py and test_rights.py
share."""

from __future__ import annotations

import copy
from collections.abc import AsyncIterator, Callable
from contextlib import asynccontextmanager
from typing import Any

import anyio
import httpx
from mcp import ClientSession
from mcp.server.mcpserver import MCPServer
from mcp.shared.memory import create_client_server_memory_streams

from benethos_mailbox_client import MailboxClient
from benethos_mailbox_mcp import server

LIST_CHANGED = "notifications/tools/list_changed"
READ = ["get_message", "get_attachment", "list_all_messages", "list_folders"]
ME: dict[str, Any] = {
    "user_id": "usr_1",
    "name": "Claude",
    "accounts": [
        {
            "id": "acc_1",
            "email": "me@example.com",
            "display_name": "Me",
            "operations": READ,
        }
    ],
    "operations": [],
}


def me_with(*operations: str) -> dict[str, Any]:
    """``ME`` whose account allows ``operations`` beside reading."""
    me = copy.deepcopy(ME)
    me["accounts"][0]["operations"] = [*READ, *operations]
    return me


class Service:
    """``/v1/me`` of the REST API: ``me`` with ``status``, or no answer at
    all while ``down``. Counts what it was asked."""

    def __init__(self, me: dict[str, Any]) -> None:
        self.me, self.status, self.down = me, 200, False
        self.asked = 0

    def __call__(self, request: httpx.Request) -> httpx.Response:
        self.asked += 1
        if self.down:
            raise httpx.ConnectError("refused", request=request)
        if self.status != 200:
            error = {"code": "unauthorized", "message": "invalid token"}
            return httpx.Response(self.status, json={"error": error})
        return httpx.Response(200, json=self.me)

    def connect(self) -> MailboxClient:
        return MailboxClient(
            "https://mail.test", "tok", transport=httpx.MockTransport(self)
        )


class Connected:
    """A client on a server, and the notifications it was sent."""

    def __init__(self, session: ClientSession, received: list[str]) -> None:
        self.session, self.received = session, received

    async def tools(self) -> list[str]:
        return [tool.name for tool in (await self.session.list_tools()).tools]

    async def told(self, times: int = 1) -> None:
        """Waits until the client was told of a changed list ``times``."""
        await until(lambda: self.received.count(LIST_CHANGED) >= times)


async def until(done: Callable[[], bool], within: float = 3.0) -> None:
    with anyio.fail_after(within):
        while not done():
            await anyio.sleep(0.005)


@asynccontextmanager
async def connected(built: MCPServer) -> AsyncIterator[Connected]:
    """A real client on ``built``, the server as a task beside it."""
    received: list[str] = []

    async def handler(message: Any) -> None:
        method = getattr(getattr(message, "root", message), "method", None)
        if method is not None:
            received.append(method)

    # The SDK's own runner, as stdio has it: the test harness reaches the
    # low-level server, the server itself does not.
    low = built._lowlevel_server
    async with (
        create_client_server_memory_streams() as (client_end, server_end),
        anyio.create_task_group() as tasks,
    ):
        tasks.start_soon(low.run, *server_end, low.create_initialization_options())
        async with ClientSession(*client_end, message_handler=handler) as session:
            await session.initialize()
            yield Connected(session, received)
        tasks.cancel_scope.cancel()


def following(
    service: Service, operations: list[str], every: float = 0.01
) -> MCPServer:
    """A server that started with ``operations`` and asks ``service``
    every ``every`` seconds."""
    return server.build_server(operations, service.connect, every)
