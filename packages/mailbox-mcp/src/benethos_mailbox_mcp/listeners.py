"""The clients a server tells that its tool list changed.

A client may ignore a notification for a capability the server did not
announce. The SDK's runners build the answer to ``initialize`` without
``tools.listChanged``, so the middleware sets it there. It also notes the
connection behind every message it sees, a list request as much as a
tool call: Claude Desktop starts a stdio server twice, and the process it
asks for the list is not the one it calls tools on.

The SDK makes a session per request and throws it away, so the
connection is what lasts. Clients on the protocol of 2026-07-28 learn of
a change through ``subscriptions/listen`` instead, which the bus serves.
"""

from __future__ import annotations

import weakref
from typing import Any

from mcp.server.connection import Connection
from mcp.server.context import CallNext, HandlerResult, ServerRequestContext
from mcp.server.subscriptions import InMemorySubscriptionBus, ToolsListChanged


class Listeners:
    """The connections of one server, and the bus of its listen streams."""

    def __init__(self) -> None:
        self.bus = InMemorySubscriptionBus()
        # Weak: a connection that ended goes with its client.
        self._connections: weakref.WeakSet[Connection] = weakref.WeakSet()

    async def middleware(
        self, ctx: ServerRequestContext[Any, Any], call_next: CallNext
    ) -> HandlerResult:
        """Notes the connection, and announces ``tools.listChanged``."""
        # The SDK names the connection of a session only privately.
        # test_listeners.py connects a real client, so a release that
        # renames it fails there and not in a client.
        self._connections.add(ctx.session._connection)
        result = await call_next(ctx)
        if ctx.method == "initialize" and isinstance(result, dict):
            tools = result.get("capabilities", {}).get("tools")
            if isinstance(tools, dict):
                tools["listChanged"] = True
        return result

    async def tell(self) -> int:
        """Tells every client that the tool list changed. The number of
        connections told, for the log."""
        await self.bus.publish(ToolsListChanged())
        connections = list(self._connections)
        for connection in connections:
            # Best effort: a connection that broke drops it and says so
            # in the SDK's log.
            await connection.send_tool_list_changed()
        return len(connections)
