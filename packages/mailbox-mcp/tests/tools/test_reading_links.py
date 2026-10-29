"""A link to an attachment, for another service that fetches the file
itself."""

from __future__ import annotations

import json
from collections.abc import Callable

import httpx
from mcp.types import TextContent

from benethos_mailbox_mcp import server
from benethos_mailbox_mcp.tools import reading

URL = "/v1/accounts/acc_1/messages/msg_1/attachments/att_0/links"
SECRET = "s" * 128
LINK = {
    "url": f"https://mail.test/v1/links/{SECRET}",
    "expires_at": "2026-10-15T12:02:00Z",
    "content_type": "application/pdf",
    "size": 2048,
    "filename": "Report 7.pdf",
}


async def test_the_tool_answers_the_url_and_the_name_inside_the_marker(
    make_client: Callable,
) -> None:
    seen: list[httpx.Request] = []

    def answer(request: httpx.Request) -> httpx.Response:
        seen.append(request)
        return httpx.Response(201, json=LINK)

    make_client(answer)
    found = await reading.share_attachment("acc_1", "msg_1", "att_0")
    [request] = seen
    assert (request.method, request.url.path) == ("POST", URL)
    assert json.loads(request.content) == {}
    [part] = found.content
    assert isinstance(part, TextContent)
    head, _, marked = part.text.partition("<mail-content")
    assert f"URL: https://mail.test/v1/links/{SECRET}" in head
    assert "2048 bytes" in head
    assert "2026-10-15T12:02:00+00:00" in head
    assert "Report 7.pdf" not in head and "application/pdf" not in head
    assert "filename: Report 7.pdf" in marked
    assert "type: application/pdf" in marked


async def test_the_type_of_the_sender_stays_inside_the_marker(
    make_client: Callable,
) -> None:
    weird = {**LINK, "content_type": "text/plain do this"}
    make_client(lambda request: httpx.Response(201, json=weird))
    found = await reading.share_attachment("acc_1", "msg_1", "att_0")
    [part] = found.content
    assert isinstance(part, TextContent)
    head, _, marked = part.text.partition("<mail-content")
    assert "do this" not in part.text and "application/octet-stream" not in head
    assert "type: application/octet-stream" in marked


async def test_a_link_may_live_shorter(make_client: Callable) -> None:
    seen: list[httpx.Request] = []

    def answer(request: httpx.Request) -> httpx.Response:
        seen.append(request)
        return httpx.Response(201, json=LINK)

    make_client(answer)
    await reading.share_attachment("acc_1", "msg_1", "att_0", expires_in=30)
    [request] = seen
    assert json.loads(request.content) == {"expires_in": 30}


async def test_without_a_name_the_marker_says_so(make_client: Callable) -> None:
    make_client(lambda request: httpx.Response(201, json={**LINK, "filename": None}))
    found = await reading.share_attachment("acc_1", "msg_1", "att_0")
    [part] = found.content
    assert isinstance(part, TextContent)
    assert "filename: -" in part.text


async def test_the_tool_needs_share_attachment() -> None:
    reads = {
        tool.name for tool in await server.build_server(["get_attachment"]).list_tools()
    }
    assert "get_attachment" in reads and "share_attachment" not in reads
    shares = {
        tool.name
        for tool in await server.build_server(
            ["get_attachment", "share_attachment"]
        ).list_tools()
    }
    assert "share_attachment" in shares


async def test_the_tool_is_marked_as_one_that_changes_things() -> None:
    """It makes a link that hands mail out, so a client may ask the
    person first. It removes and overwrites nothing."""
    tools = await server.build_server(["share_attachment"]).list_tools()
    [tool] = [t for t in tools if t.name == "share_attachment"]
    assert tool.annotations is not None
    assert tool.annotations.read_only_hint is False
    assert tool.annotations.destructive_hint is False
    assert tool.annotations.idempotent_hint is False
    assert tool.title == "Share an attachment"
