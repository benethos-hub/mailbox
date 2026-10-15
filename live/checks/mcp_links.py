"""A link to an attachment through the MCP server: the first PDF the test
accounts hold, shared, fetched once without a token as another service
would, then refused. Nothing is sent, and the URL is never printed."""

from __future__ import annotations

import httpx
from mcp import ClientSession

from benethos_mailbox_client import SyncMailboxClient

from .mcp_session import mcp_session, text_of
from .run import Run

# The REST client reads the attachment for the comparison up to this.
MAX_BYTES = 50 * 1024 * 1024
GONE = {"error": {"code": "not_found", "message": "no such link"}}


async def first_pdf(session: ClientSession) -> tuple[str, str, str] | None:
    """The account, the message and the attachment of the first PDF a
    search of the test accounts finds, None without one."""
    found = await session.call_tool(
        "search_messages", {"has_attachments": True, "limit": 20}
    )
    for summary in (found.structured_content or {}).get("messages", []):
        read = await session.call_tool(
            "get_message",
            {"account_id": summary["account_id"], "message_id": summary["id"]},
        )
        pdfs = [
            line.split()[1]
            for line in text_of(read).splitlines()
            if line.startswith("attachment:") and "application/pdf" in line
        ]
        if pdfs:
            return summary["account_id"], summary["id"], pdfs[0]
    return None


async def check_links(run: Run, url: str, token: str, admin: SyncMailboxClient) -> None:
    """``token`` may read and share. The bytes of the link are those
    ``get_attachment`` of the REST API answers, once."""
    async with mcp_session(url, token) as session:
        tools = {tool.name for tool in (await session.list_tools()).tools}
        run.check(
            "a token with mail.share sees share_attachment",
            "share_attachment" in tools,
        )
        found = await first_pdf(session)
        if found is None:
            print("SKIP  no PDF attachment in the test accounts")
            return
        account_id, message_id, attachment_id = found
        shared = await session.call_tool(
            "share_attachment",
            {
                "account_id": account_id,
                "message_id": message_id,
                "attachment_id": attachment_id,
            },
        )
    said = text_of(shared)
    link = next(
        (
            line[len("URL: ") :]
            for line in said.splitlines()
            if line.startswith("URL: ")
        ),
        "",
    )
    run.check(
        "share_attachment answers a link of the service",
        not shared.is_error and link.startswith(f"{url}/v1/links/"),
        f"a secret of {len(link.rpartition('/')[2])} characters",
    )
    if not link.startswith(f"{url}/v1/links/"):
        return
    expected = admin.get_attachment(
        account_id, message_id, attachment_id, max_bytes=MAX_BYTES
    ).data
    with httpx.Client(timeout=60) as another_service:
        first = another_service.get(link)
        second = another_service.get(link)
    run.check(
        "a GET without a token hands out the bytes get_attachment answers",
        first.status_code == 200 and first.content == expected,
        f"{first.status_code}, {len(first.content)} bytes",
    )
    run.check(
        "the link holds once: a second GET answers the same 404",
        second.status_code == 404 and second.json() == GONE,
        str(second.status_code),
    )
