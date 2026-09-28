"""list_accounts: the accounts, and what the token may do on each."""

from __future__ import annotations

from typing import Any

from .. import render
from . import drafts, reading, sending, writing
from .base import Tool, client

# What list_accounts reports a caller may do, in this order: what the
# tools of that kind need.
CAPABILITIES = ("read", "write", "drafts", "send")
# The tools of every kind, whose needs name the kinds.
_KINDS = (*reading.TOOLS, *writing.TOOLS, *drafts.TOOLS, *sending.TOOLS)


async def list_accounts() -> list[dict[str, Any]]:
    """The mail accounts you may use: id, address and what you may do there
    (read, write, drafts, send). Other tools take the account id."""
    me = await client().me()
    return [
        render.account(account, _capabilities(account.operations))
        for account in me.accounts
    ]


def _capabilities(operations: frozenset[str]) -> list[str]:
    """Which kinds of tool ``operations`` unlock."""
    kinds = {tool.kind for tool in _KINDS if tool.kind and tool.needs & operations}
    return [kind for kind in CAPABILITIES if kind in kinds]


TOOLS = (Tool(list_accounts, "List accounts", frozenset(), open_world=False),)
