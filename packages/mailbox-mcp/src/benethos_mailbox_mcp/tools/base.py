"""What every tool module shares: the record of a tool with its
annotations, the REST client all tools call, and a result of text and
images. The one module of ``tools`` that imports the MCP library."""

from __future__ import annotations

import base64
from collections.abc import Callable
from dataclasses import dataclass
from typing import Any

from mcp.types import CallToolResult, ImageContent, TextContent

from ..client import MailboxApiClient

# What a tool answers when it hands over more than text.
ToolResult = CallToolResult

MAX_LIMIT = 50


_client: MailboxApiClient | None = None


def use_client(client: MailboxApiClient | None) -> MailboxApiClient | None:
    """The client the tools call from now on: one made for a test, or
    ``None`` so the next call makes one from the environment. Returns the
    one before, for its owner to close."""
    global _client
    before, _client = _client, client
    return before


def client() -> MailboxApiClient:
    """The shared REST client, created on first use."""
    global _client
    if _client is None:
        _client = MailboxApiClient()
    return _client


@dataclass(frozen=True)
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
