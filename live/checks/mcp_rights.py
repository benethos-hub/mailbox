"""The MCP server follows its token's rights while it runs: an admin takes
``mail.share`` from its user and gives it back, then disables the user.
The server must tell its client each time and list the tools that are
left, at last server_status alone. It asks every second here. Nothing
is read from a mailbox and nothing is sent."""

from __future__ import annotations

import secrets

import anyio
from mcp import ClientSession

from benethos_mailbox_client import Grant, SyncMailboxClient

from .mcp_session import mcp_session
from .run import Run

SHARE = "share_attachment"
LIST_CHANGED = "notifications/tools/list_changed"
# How often the server asks, and how long the check waits for a change.
ASK_SECONDS = "1"
WAIT_SECONDS = 15


async def _tools(session: ClientSession) -> set[str]:
    return {tool.name for tool in (await session.list_tools()).tools}


async def _told(notified: list[str], times: int) -> bool:
    """Whether the client was told of a changed list ``times`` in time."""
    with anyio.move_on_after(WAIT_SECONDS):
        while notified.count(LIST_CHANGED) < times:
            await anyio.sleep(0.1)
        return True
    return False


async def check_rights(
    run: Run, url: str, admin: SyncMailboxClient, account_ids: list[str]
) -> None:
    def grant(*allow: str) -> list[Grant]:
        return [Grant(tuple(account_ids), allow)]

    user = admin.create_user(
        f"live check rights {secrets.token_hex(3)}",
        grants=grant("mail.read", "mail.share"),
    )
    token = admin.create_token(user.id, "live").secret.get_secret_value()
    notified: list[str] = []
    settings = {"MAILBOX_MCP_RIGHTS_SECONDS": ASK_SECONDS}
    async with mcp_session(url, token, settings=settings, notified=notified) as session:
        capabilities = session.server_capabilities
        run.check(
            "the server announces that its tool list may change",
            capabilities is not None
            and capabilities.tools is not None
            and bool(capabilities.tools.list_changed),
        )
        run.check(
            "the user may share: share_attachment", SHARE in await _tools(session)
        )

        admin.update_user(user.id, grants=grant("mail.read"))
        told = await _told(notified, 1)
        tools = await _tools(session)
        run.check(
            "mail.share taken away: the client is told, share_attachment is gone",
            told and SHARE not in tools and "get_attachment" in tools,
            f"{len(tools)} tools",
        )

        admin.update_user(user.id, grants=grant("mail.read", "mail.share"))
        told = await _told(notified, 2)
        run.check(
            "mail.share given back: the client is told, share_attachment is back",
            told and SHARE in await _tools(session),
        )

        # One refusal of the token, which counts against this address once:
        # the server asks no more after it.
        admin.update_user(user.id, disabled=True)
        told = await _told(notified, 3)
        tools = await _tools(session)
        run.check(
            "the user disabled: the client is told, server_status alone is left",
            told and tools == {"server_status"},
            f"{len(tools)} tools",
        )
