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
