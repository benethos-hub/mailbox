from __future__ import annotations

import asyncio
import contextvars
import json
import logging
import re
from collections.abc import Callable
from pathlib import Path

import httpx
import pytest
from mcp.server.mcpserver.exceptions import ToolError as SdkToolError

from benethos_mailbox_client import MailboxClient
from benethos_mailbox_mcp import server
from benethos_mailbox_mcp import tools as catalogue
from benethos_mailbox_mcp.errors import (
    ApiError,
    ConfigurationError,
    ServiceTimeoutError,
    ServiceUnavailableError,
    ToolError,
)
from benethos_mailbox_mcp.tools import reading, writing

READ = ["get_message", "list_all_messages", "list_folders", "list_messages"]
ME = {
    "user_id": "usr_1",
    "name": "Claude",
    "accounts": [
        {
            "id": "acc_1",
            "email": "me@example.com",
            "display_name": "Me",
            "operations": [*READ, "create_draft"],
        }
    ],
    "operations": [],
}


# --- which tools exist ----------------------------------------------------------------


async def names(operations: list[str]) -> set[str]:
    return {tool.name for tool in await server.build_server(operations).list_tools()}


async def test_only_what_the_token_may_do() -> None:
    assert await names([]) == {"list_accounts", "server_status"}
    assert await names(READ) == {
        "list_accounts",
        "server_status",
        "list_folders",
        "search_messages",
        "get_message",
    }


async def test_read_tools_are_marked_read_only() -> None:
    for tool in await server.build_server(READ).list_tools():
        assert tool.annotations is not None
        assert tool.annotations.read_only_hint is True


async def test_allowed_operations_from_me(api: Callable) -> None:
    api(routes={"/v1/me": {**ME, "operations": ["list_users"]}})
    assert await server.allowed_operations() == {*READ, "create_draft", "list_users"}


async def test_the_start_warns_who_may_read_and_send_anywhere(
    api: Callable, caplog: pytest.LogCaptureFixture
) -> None:
    account = {**ME["accounts"][0], "warnings": ["read_and_send_anywhere"]}  # type: ignore[index]
    api(routes={"/v1/me": {**ME, "accounts": [account]}})
    await server.allowed_operations()
    assert "me@example.com: this token can read mail and send it" in caplog.text


# --- the tools through the server -----------------------------------------------------


async def test_whats_new_needs_a_change_right() -> None:
    assert "whats_new" not in await names(READ)
    assert "whats_new" in await names(["list_all_changes"])
    assert "whats_new" in await names(["list_changes"])


async def test_a_tool_call_through_the_server(api: Callable) -> None:
    api(routes={"/v1/accounts/acc_1/folders": [
        {"id": "f1", "name": "Inbox", "role": "inbox", "unread": 2, "total": 5}
    ]})  # fmt: skip
    result = await server.build_server(READ).call_tool(
        "list_folders", {"account_id": "acc_1"}
    )
    assert "Inbox" in json.dumps(result, default=str)


EVERY_OPERATION = {need for tool in catalogue.TOOLS for need in tool.needs}


@pytest.mark.parametrize(
    ("tool", "arguments", "field"),
    [
        ("search_messages", {"limit": 0}, "limit"),
        ("search_messages", {"limit": catalogue.MAX_LIMIT + 1}, "limit"),
        ("whats_new", {"limit": reading.MAX_CHANGES + 1}, "limit"),
        (
            "get_message",
            {"account_id": "acc_1", "message_id": "m", "max_chars": 199},
            "max_chars",
        ),
        (
            "get_attachment",
            {
                "account_id": "acc_1",
                "message_id": "m",
                "attachment_id": "a",
                "pages": reading.MAX_PAGES + 1,
            },
            "pages",
        ),
        (
            "update_messages",
            {"account_id": "acc_1", "message_ids": [], "unread": True},
            "message_ids",
        ),
        (
            "update_messages",
            {
                "account_id": "acc_1",
                "message_ids": [f"m{n}" for n in range(writing.MAX_BATCH + 1)],
                "unread": True,
            },
            "message_ids",
        ),
        ("create_folder", {"account_id": "acc_1", "name": "x" * 201}, "name"),
        (
            "update_folder",
            {"account_id": "acc_1", "folder_id": "f", "name": "x" * 201},
            "name",
        ),
        (
            "send_message",
            {
                "account_id": "acc_1",
                "to": [f"r{n}@example.com" for n in range(101)],
                "subject": "s",
                "text": "t",
            },
            "to",
        ),
    ],
)
async def test_the_server_refuses_arguments_out_of_bounds(
    api: Callable, tool: str, arguments: dict[str, object], field: str
) -> None:
    """The bounds live in the tools' signatures: the server checks them
    before a tool runs, and nothing reaches the service."""
    fake = api([])
    with pytest.raises(SdkToolError, match=rf"(?s)validation error.*\n{field}\n"):
        await server.build_server(EVERY_OPERATION).call_tool(tool, arguments)
    assert fake.calls == []


# --- the client of each server -----------------------------------------------------


def test_a_tool_outside_a_server_has_no_client() -> None:
    with pytest.raises(RuntimeError, match="no REST client"):
        catalogue.client()


async def test_each_server_has_a_client_of_its_own() -> None:
    """Two servers in one process, such as in tests or behind a reload,
    share no client. The MCP library runs a tool in the context of the
    transport that read the call, not of the lifespan: here a context of
    its own, empty. Each server closes its client when it stops."""
    asked: list[str] = []
    made: list[MailboxClient] = []

    def connect_to(host: str) -> Callable[[], MailboxClient]:
        def answer(request: httpx.Request) -> httpx.Response:
            # Each server asks the service's version as it starts.
            if request.url.path != "/health":
                asked.append(request.url.host)
            return httpx.Response(200, json=ME)

        def connect() -> MailboxClient:
            made.append(
                MailboxClient(
                    f"https://{host}", "tok", transport=httpx.MockTransport(answer)
                )
            )
            return made[-1]

        return connect

    first = server.build_server(READ, connect_to("one.test"))
    second = server.build_server(READ, connect_to("two.test"))
    assert first.settings.lifespan is not None
    assert second.settings.lifespan is not None
    loop = asyncio.get_running_loop()
    async with first.settings.lifespan(first), second.settings.lifespan(second):
        for built in (first, second, first):
            call = built.call_tool("list_accounts", {})
            await loop.create_task(call, context=contextvars.Context())
    assert asked == ["one.test", "two.test", "one.test"]
    assert all(client._http.is_closed for client in made)


async def test_a_server_without_a_client_leaves_the_one_around(
    make_client: Callable,
) -> None:
    test = make_client(lambda _: httpx.Response(200, json=[]))
    with catalogue.calling(None):
        assert catalogue.client() is test
    own = MailboxClient(base_url="https://own.test", token="secret")
    with catalogue.calling(own):
        assert catalogue.client() is own
    assert catalogue.client() is test
    await own.aclose()


# title, read-only, destructive, idempotent, open world
HINTS = {
    "list_accounts": ("List accounts", True, None, None, False),
    "list_folders": ("List folders", True, None, None, True),
    "search_messages": ("Search mail", True, None, None, True),
    "get_message": ("Read a message", True, None, None, True),
    "get_thread": ("Read a conversation", True, None, None, True),
    "whats_new": ("What is new", True, None, None, True),
    "get_attachment": ("Get an attachment", True, None, None, True),
    "share_attachment": ("Share an attachment", False, False, False, True),
    "update_messages": ("Change messages", False, True, True, True),
    "create_folder": ("Create a folder", False, False, False, True),
    "update_folder": ("Rename or move a folder", False, True, True, True),
    "list_drafts": ("List drafts", True, None, None, True),
    "create_draft": ("Write a draft", False, False, False, True),
    "update_draft": ("Replace a draft", False, True, True, True),
    "delete_draft": ("Delete a draft", False, True, True, True),
    "send_message": ("Send a mail", False, True, False, True),
    "send_draft": ("Send a draft", False, True, False, True),
    "server_status": ("Server status", True, None, None, False),
}


README = Path(__file__).resolve().parents[1] / "README.md"


async def test_the_readme_lists_every_tool() -> None:
    """The tool table of the README, which the service's UI repeats."""
    every = {need for tool in catalogue.TOOLS for need in tool.needs}
    tools = {tool.name for tool in await server.build_server(every).list_tools()}
    listed = re.findall(r"^\| `(\w+)` \|", README.read_text(encoding="utf-8"), re.M)
    assert set(listed) == tools and len(listed) == len(tools)


async def test_every_tool_carries_its_title_and_hints() -> None:
    every = {need for tool in catalogue.TOOLS for need in tool.needs}
    tools = await server.build_server(every).list_tools()
    assert {tool.name for tool in tools} == set(HINTS)
    for tool in tools:
        hints = tool.annotations
        assert hints is not None
        assert tool.title == hints.title
        found = (
            hints.title,
            hints.read_only_hint,
            hints.destructive_hint,
            hints.idempotent_hint,
            hints.open_world_hint,
        )
        assert found == HINTS[tool.name], tool.name
        assert len(tool.description or "") < 700, tool.name


@pytest.mark.parametrize(
    ("error", "said"),
    [
        (
            ApiError(403, "recipient_not_allowed", "no grant allows a@x.org"),
            "recipient_not_allowed (HTTP 403)",
        ),
        (ServiceUnavailableError("gone"), "mailbox-service is not reachable"),
        (ServiceTimeoutError("slow"), "mailbox-service did not answer in time"),
        (ConfigurationError("no token"), "the REST client is not configured"),
        (ToolError("not an address: a@x.org"), "the arguments were refused"),
    ],
)
async def test_a_failed_tool_is_a_warning_without_its_arguments(
    caplog: pytest.LogCaptureFixture, error: Exception, said: str
) -> None:
    """Each error reaches the model as a ToolError with its message."""

    async def send_message(account_id: str, to: list[str]) -> str:
        raise error

    logged = server._logged(send_message, server._Held())
    with pytest.raises(ToolError) as caught:
        await logged("acc_1", to=["a@x.org"])
    assert str(caught.value) == str(error)
    [record] = caplog.records
    assert record.levelno == logging.WARNING
    assert record.getMessage() == f"tool send_message failed: {said}"
    assert "a@x.org" not in caplog.text


async def test_a_tool_error_logs_its_kind(caplog: pytest.LogCaptureFixture) -> None:
    """A PDF that takes too long is no refused argument."""

    async def get_attachment() -> str:
        raise ToolError("took longer than 30 seconds", kind="the PDF took too long")

    with pytest.raises(ToolError):
        await server._logged(get_attachment, server._Held())()
    [record] = caplog.records
    assert record.getMessage() == "tool get_attachment failed: the PDF took too long"
