"""The MCP server over stdio, the way Claude starts it, as a session of
the script's own, and the text of a tool's answer."""

from __future__ import annotations

import os
from collections.abc import AsyncIterator
from contextlib import asynccontextmanager
from typing import Any

from mcp import ClientSession
from mcp.client.stdio import StdioServerParameters, stdio_client

from .processes import program


def text_of(result: Any) -> str:
    return "".join(getattr(part, "text", "") for part in result.content)


@asynccontextmanager
async def mcp_session(url: str, token: str) -> AsyncIterator[ClientSession]:
    """``benethos-mailbox-mcp`` over stdio with ``token``."""
    params = StdioServerParameters(
        command=program("benethos-mailbox-mcp"),
        env={**os.environ, "MAILBOX_SERVICE_URL": url, "MAILBOX_SERVICE_TOKEN": token},
    )
    async with (
        stdio_client(params) as (read, write),
        ClientSession(read, write) as session,
    ):
        await session.initialize()
        yield session
