"""Draft tools: list, create, replace and delete drafts. Nothing is sent."""

from __future__ import annotations

from collections.abc import Callable

import pytest

from benethos_mailbox_mcp import server
from benethos_mailbox_mcp.errors import ToolError

DRAFTS = "/v1/accounts/acc_1/drafts"
SUMMARY = {
    "id": "msg_d",
    "date": "2026-09-24T10:00:00Z",
    "from": {"email": "me@example.com"},
    "to": [{"email": "bob@example.com", "name": "Bob"}],
    "subject": "Hello",
    "snippet": "not needed",
}


async def test_list_drafts(api: Callable) -> None:
    handler = api({"items": [SUMMARY], "next_cursor": None})
    assert await server.list_drafts("acc_1", limit=5) == {
        "drafts": [
            {
                "id": "msg_d",
                "date": "2026-09-24T10:00:00Z",
                "to": "Bob <bob@example.com>",
                "subject": "Hello",
            }
        ],
        "next_cursor": None,
    }
    assert handler.calls == [("GET", DRAFTS, {"limit": "5"}, None)]


async def test_create_draft(api: Callable) -> None:
    handler = api(SUMMARY, status=201)
    result = await server.create_draft(
        "acc_1",
        to=["Bob <bob@example.com>"],
        bcc=["carol@example.com"],
        subject="Hello",
        text="Hi Bob",
    )
    assert result["id"] == "msg_d"
    [(method, path, _, body)] = handler.calls
    assert (method, path) == ("POST", DRAFTS)
    assert body == {
        "to": [{"email": "bob@example.com", "name": "Bob"}],
        "cc": [],
        "bcc": [{"email": "carol@example.com"}],
        "subject": "Hello",
        "text": "Hi Bob",
    }


async def test_a_reply_draft_names_its_original(api: Callable) -> None:
    handler = api(SUMMARY, status=201)
    await server.create_draft(
        "acc_1", text="Thanks", original_id="msg_1", action="reply_all"
    )
    body = handler.calls[0].body
    assert body["reference"] == {"message_id": "msg_1", "action": "reply_all"}
    assert body["to"] == []


async def test_not_an_address(api: Callable) -> None:
    handler = api(SUMMARY)
    with pytest.raises(ToolError, match="not an address: Bob"):
        await server.create_draft("acc_1", to=["Bob"])
    assert handler.calls == []


async def test_update_draft_replaces_it(api: Callable) -> None:
    handler = api(SUMMARY)
    await server.update_draft("acc_1", "msg_d", to=["bob@example.com"], text="v2")
    [(method, path, _, body)] = handler.calls
    assert (method, path) == ("PUT", f"{DRAFTS}/msg_d")
    assert body["text"] == "v2" and body["subject"] == ""
    assert "keep_attachments" not in body
    await server.update_draft("acc_1", "msg_d", text="v3", keep_attachments=["att_0"])
    assert handler.calls[-1].body["keep_attachments"] == ["att_0"]


async def test_delete_draft(api: Callable) -> None:
    handler = api(None)
    assert await server.delete_draft("acc_1", "msg_d") == "draft msg_d deleted"
    assert handler.calls == [("DELETE", f"{DRAFTS}/msg_d", {}, None)]


async def test_registered_by_the_right_and_marked() -> None:
    rights = ["list_drafts", "create_draft", "update_draft", "delete_draft"]
    tools = {t.name: t for t in await server.build_server(rights).list_tools()}
    assert set(tools) == {"list_accounts", *rights}
    hints = {
        name: (t.annotations.read_only_hint, t.annotations.destructive_hint)  # type: ignore[union-attr]
        for name, t in tools.items()
    }
    assert hints["list_drafts"] == (True, None)
    assert hints["create_draft"] == (False, False)
    assert hints["update_draft"] == (False, True)
    assert hints["delete_draft"] == (False, True)


async def test_only_create_draft_with_that_right() -> None:
    names = {t.name for t in await server.build_server(["create_draft"]).list_tools()}
    assert names == {"list_accounts", "create_draft"}


async def test_a_draft_in_html(api: Callable) -> None:
    handler = api(SUMMARY, status=201)
    await server.create_draft("acc_1", html="<p>Hi</p>", text="Hi")
    body = handler.calls[0].body
    assert (body["html"], body["text"]) == ("<p>Hi</p>", "Hi")
