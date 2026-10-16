"""Telling clients that the tool list changed, over the wire.

A real client connects through the SDK's own runner, because that is
the path a server breaks on without any other test noticing: the runner
builds a session per request, so a server that remembered sessions would
tell nobody. These tests also hold the one private name the server
reads of the SDK, the connection of a session.
"""

from __future__ import annotations

import gc

from mcp.server.subscriptions import ServerEvent, ToolsListChanged

from benethos_mailbox_mcp import server
from benethos_mailbox_mcp.listeners import Listeners

from .rights_helpers import ME, READ, Service, connected, until


async def test_the_capability_is_announced() -> None:
    """A client may ignore a notification for a capability nobody
    promised, and the SDK's runner promises none."""
    built = server.build_server(READ, Service(ME).connect)
    async with connected(built) as client:
        result = client.session.server_capabilities
        assert result is not None
        assert result.tools is not None
        assert result.tools.list_changed is True


async def test_a_client_that_only_lists_is_told() -> None:
    """Claude Desktop lists in one process and calls tools in another:
    a list request is enough to be told."""
    listeners = Listeners()
    built = server.build_server(READ, Service(ME).connect)
    built.middleware.append(listeners.middleware)
    async with connected(built) as client:
        await client.tools()
        assert await listeners.tell() == 1
        await client.told()


async def test_a_client_that_left_is_forgotten() -> None:
    listeners = Listeners()
    built = server.build_server(READ, Service(ME).connect)
    built.middleware.append(listeners.middleware)
    async with connected(built) as client:
        await client.tools()
    gc.collect()
    await until(lambda: not list(listeners._connections))
    assert await listeners.tell() == 0


async def test_a_listen_stream_learns_of_it_on_the_bus() -> None:
    """Clients of the protocol of 2026-07-28 learn of a change through
    ``subscriptions/listen``, which the bus serves."""
    listeners = Listeners()
    events: list[ServerEvent] = []
    listeners.bus.subscribe(events.append)
    await listeners.tell()
    assert events == [ToolsListChanged()]
