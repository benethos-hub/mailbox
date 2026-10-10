"""What every tool module shares: the record of a tool with its
annotations, the REST client all tools call, and a result of text and
images. The one module of ``tools`` that imports the MCP library."""

from __future__ import annotations

import base64
from collections.abc import Callable, Iterator
from contextlib import contextmanager
from contextvars import ContextVar
from dataclasses import dataclass
from typing import Any

from mcp.types import CallToolResult, ImageContent, TextContent

from ..client import MailboxClient

# What a tool answers when it hands over more than text.
ToolResult = CallToolResult

MAX_LIMIT = 50


# The client of the server whose tool runs now. Each server makes its own
# in its lifespan, so two servers in one process share none. The MCP
# library runs a tool in the context of the transport that read the call,
# not of the lifespan: the server sets it around each call.
_calling: ContextVar[MailboxClient | None] = ContextVar("calling", default=None)
# The client of a test that calls a tool without a server's lifespan.
_for_tests: MailboxClient | None = None


@contextmanager
def calling(made: MailboxClient | None) -> Iterator[None]:
    """``made`` for the tools called inside. None leaves the one of a
    test."""
    token = _calling.set(made)
    try:
        yield
    finally:
        _calling.reset(token)


def use_client(client: MailboxClient | None) -> MailboxClient | None:
    """For tests: the client the tools call outside a server's lifespan.
    Returns the one before, for its owner to close."""
    global _for_tests
    before, _for_tests = _for_tests, client
    return before


def client() -> MailboxClient:
    """The REST client of the server the tool runs in."""
    found = _calling.get() or _for_tests
    if found is None:
        raise RuntimeError("no REST client: a tool runs inside a server's lifespan")
    return found


@dataclass(frozen=True, slots=True)
class Tool:
    fn: Callable[..., Any]
    # What a client shows to a person.
    title: str
    # Registered when the token holds any of these on at least one account.
    needs: frozenset[str]
    # What list_accounts calls tools of this kind. None for list_accounts.
    kind: str | None = None
    read_only: bool = True
    # The hints below mean something for tools that change things only.
    # Destructive: it can remove or overwrite something, or send mail.
    destructive: bool = False
    # Idempotent: the same call again changes nothing more.
    idempotent: bool = False
    # Open world: it reaches mail, which comes from and goes to anyone.
    # Only list_accounts stays inside this service.
    open_world: bool = True


def reads(fn: Callable[..., Any], title: str, *needs: str, kind: str = "read") -> Tool:
    return Tool(fn, title, frozenset(needs), kind)


def changes(
    fn: Callable[..., Any],
    title: str,
    kind: str,
    *needs: str,
    destructive: bool,
    idempotent: bool,
) -> Tool:
    return Tool(
        fn,
        title,
        frozenset(needs),
        kind,
        read_only=False,
        destructive=destructive,
        idempotent=idempotent,
    )


def result(text: str, images: list[tuple[bytes, str]] | None = None) -> ToolResult:
    content: list[TextContent | ImageContent] = [TextContent(type="text", text=text)]
    content += [
        ImageContent(
            type="image", data=base64.b64encode(data).decode("ascii"), mimeType=kind
        )
        for data, kind in images or []
    ]
    return CallToolResult(content=list(content))
