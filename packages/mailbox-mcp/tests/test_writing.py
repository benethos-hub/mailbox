"""Tools that change mail: update_messages and create_folder."""

from __future__ import annotations

import json
from collections.abc import Callable
from typing import Any

import httpx
import pytest

from benethos_mailbox_mcp import server
from benethos_mailbox_mcp.errors import ToolError

FOLDERS = [
    {"id": "fld_inbox", "name": "INBOX", "role": "inbox"},
    {"id": "fld_archive", "name": "Archive", "role": "archive"},
    {"id": "fld_work", "name": "Work", "role": None},
]
BATCH = "/v1/accounts/acc_1/messages/batch"


def api(answer: Any = None) -> Callable[[httpx.Request], httpx.Response]:
    """Folders on GET, ``answer`` on POST; records every request's body."""

    def handle(request: httpx.Request) -> httpx.Response:
        body = json.loads(request.content) if request.content else None
        handle.calls.append((request.method, request.url.path, body))  # type: ignore[attr-defined]
        if request.method == "GET":
            return httpx.Response(200, json=FOLDERS)
        return httpx.Response(200, json=answer)

    handle.calls = []  # type: ignore[attr-defined]
    return handle


def posted(handler: Any) -> list[tuple[str, Any]]:
    return [(path, body) for method, path, body in handler.calls if method == "POST"]


# --- update_messages ------------------------------------------------------------------


async def test_marks_and_reports_each_id(make_client: Callable) -> None:
    handler = api(
        {
            "results": [
                {"id": "msg_1", "ok": True, "message": {"id": "msg_1"}},
                {
                    "id": "msg_2",
                    "ok": False,
                    "error": {"code": "not_found", "message": "no such message"},
                },
            ]
        }
    )
    make_client(handler)
    result = await server.update_messages(
        "acc_1", ["msg_1", "msg_2"], unread=False, starred=True
    )
    assert posted(handler) == [
        (
            BATCH,
            {
                "ids": ["msg_1", "msg_2"],
                "action": "update",
                "changes": {"unread": False, "starred": True},
            },
        )
    ]
    assert result == {
        "done": ["msg_1"],
        "failed": [{"id": "msg_2", "error": "no such message"}],
    }


async def test_move_by_role(make_client: Callable) -> None:
    """The API resolves roles: the server passes one on and asks for no
    folders."""
    handler = api({"results": [{"id": "msg_1", "ok": True}]})
    make_client(handler)
    await server.update_messages("acc_1", ["msg_1"], move_to="archive")
    assert [method for method, _, _ in handler.calls] == ["POST"]
    assert posted(handler)[0][1]["changes"] == {"folder_ids": ["archive"]}


async def test_move_by_id_asks_for_no_folders(make_client: Callable) -> None:
    handler = api({"results": [{"id": "msg_1", "ok": True}]})
    make_client(handler)
    await server.update_messages("acc_1", ["msg_1"], move_to="fld_work")
    assert [method for method, _, _ in handler.calls] == ["POST"]
    assert posted(handler)[0][1]["changes"] == {"folder_ids": ["fld_work"]}


async def test_a_role_the_account_lacks(make_client: Callable) -> None:
    def refuse(request: httpx.Request) -> httpx.Response:
        error = {"code": "not_found", "message": "the account has no junk folder"}
        return httpx.Response(404, json={"error": error})

    make_client(refuse)
    with pytest.raises(ToolError, match="has no junk folder"):
        await server.update_messages("acc_1", ["msg_1"], move_to="junk")


async def test_trash(make_client: Callable) -> None:
    handler = api({"results": [{"id": "msg_1", "ok": True}]})
    make_client(handler)
    assert await server.update_messages("acc_1", ["msg_1"], trash=True) == {
        "done": ["msg_1"],
        "failed": [],
    }
    assert posted(handler) == [(BATCH, {"ids": ["msg_1"], "action": "delete"})]


async def test_trash_goes_alone(make_client: Callable) -> None:
    make_client(api())
    with pytest.raises(ToolError, match="alone"):
        await server.update_messages("acc_1", ["msg_1"], trash=True, unread=False)


async def test_nothing_to_change(make_client: Callable) -> None:
    make_client(api())
    with pytest.raises(ToolError, match="nothing to change"):
        await server.update_messages("acc_1", ["msg_1"])


# --- create_folder --------------------------------------------------------------------


async def test_create_folder(make_client: Callable) -> None:
    handler = api({"id": "fld_new", "name": "Invoices", "role": None, "total": 0})
    make_client(handler)
    assert await server.create_folder("acc_1", "Invoices") == {
        "id": "fld_new",
        "name": "Invoices",
    }
    assert posted(handler) == [("/v1/accounts/acc_1/folders", {"name": "Invoices"})]


async def test_create_folder_below_a_role(make_client: Callable) -> None:
    handler = api({"id": "fld_new", "name": "2026"})
    make_client(handler)
    await server.create_folder("acc_1", "2026", parent="archive")
    assert posted(handler)[0][1] == {"name": "2026", "parent_id": "archive"}


# --- registration ---------------------------------------------------------------------


async def test_registered_by_the_right_and_marked() -> None:
    tools = {
        tool.name: tool
        for tool in await server.build_server(
            ["batch_messages", "create_folder"]
        ).list_tools()
    }
    assert set(tools) == {"list_accounts", "update_messages", "create_folder"}
    update, create = tools["update_messages"], tools["create_folder"]
    assert update.annotations is not None and create.annotations is not None
    assert update.annotations.read_only_hint is False
    assert update.annotations.destructive_hint is True
    assert create.annotations.destructive_hint is False
    for tool in tools.values():
        assert len(tool.description or "") < 700, tool.name
