"""The tool that reports the accounts: list_accounts."""

from __future__ import annotations

from collections.abc import Callable

import httpx
import pytest

from benethos_mailbox_mcp.errors import ToolError
from benethos_mailbox_mcp.tools import accounts

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


async def test_list_accounts_says_what_is_allowed(api: Callable) -> None:
    api(routes={"/v1/me": ME})
    assert await accounts.list_accounts() == [
        {
            "id": "acc_1",
            "email": "me@example.com",
            "name": "Me",
            "can": ["read", "drafts"],
        }
    ]


async def test_errors_are_tool_errors(make_client: Callable) -> None:
    make_client(
        lambda _: httpx.Response(
            401, json={"error": {"code": "unauthorized", "message": "wrong token"}}
        )
    )
    with pytest.raises(ToolError, match="wrong token"):
        await accounts.list_accounts()


async def test_list_accounts_names_the_limits_on_sending(api: Callable) -> None:
    """The model knows before it sends (PERMISSIONS.md 8.8)."""
    sender = {
        **ME["accounts"][0],
        "operations": [*READ, "send_message"],
        "sending": [
            {
                "recipients": ["*@example.org"],
                "max_sends_per_day": 10,
                "sends_left": 3,
            },
            {"recipients": None, "max_sends_per_day": None, "sends_left": None},
        ],
        "warnings": ["read_and_send_anywhere"],
    }
    api(routes={"/v1/me": {**ME, "accounts": [sender]}})
    [shown] = await accounts.list_accounts()
    assert shown["can"] == ["read", "send"]
    assert shown["sending"] == [
        "only to *@example.org, at most 10 a day, 3 left now",
        "to anyone, no daily limit",
    ]
    assert "send it to any address" in shown["warning"]


async def test_no_sending_shown_without_the_right_to_send(api: Callable) -> None:
    api(routes={"/v1/me": ME})
    [shown] = await accounts.list_accounts()
    assert "sending" not in shown and "warning" not in shown
