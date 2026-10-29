"""The tool that reports the accounts: list_accounts."""

from __future__ import annotations

from collections.abc import Callable

import httpx
import pytest

from benethos_mailbox_mcp.errors import ApiError
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


async def test_list_accounts_names_what_an_account_cannot_do(api: Callable) -> None:
    """A mailbox without folders, read state, search or drafts. The API
    answers no drafts operation there, so the drafts tools are not
    offered, and the rest is named."""
    pop3 = {
        **ME["accounts"][0],
        "operations": READ,
        "capabilities": ["purge", "send"],
    }
    api(routes={"/v1/me": {**ME, "accounts": [pop3]}})
    assert await accounts.list_accounts() == [
        {
            "id": "acc_1",
            "email": "me@example.com",
            "name": "Me",
            "can": ["read"],
            "unsupported": [
                "read state",
                "stars",
                "keywords",
                "creating, renaming and deleting folders",
                "moving mail",
                "the trash",
                "search and filters",
                "drafts",
                "a mail in several folders (add_folders, remove_folders)",
                "conversations (get_thread, thread ids)",
                "a copy in the sent folder",
            ],
        }
    ]


async def test_an_account_that_can_do_everything_names_no_limits(
    api: Callable,
) -> None:
    full = {
        **ME["accounts"][0],
        "capabilities": [
            "read_state",
            "stars",
            "keywords",
            "folders",
            "move",
            "trash",
            "search",
            "drafts",
            "send",
            "labels",
            "threads",
            "sent_copy",
        ],
    }
    api(routes={"/v1/me": {**ME, "accounts": [full]}})
    [shown] = await accounts.list_accounts()
    assert shown["can"] == ["read", "drafts"] and "unsupported" not in shown


@pytest.mark.parametrize(
    ("status", "says"),
    [("needs_reauth", "sign in to the provider again"), ("connected", "last sync")],
)
async def test_an_account_that_needs_a_look(
    api: Callable, status: str, says: str
) -> None:
    ailing = {
        **ME["accounts"][0],
        "status": status,
        "attention": True,
        "last_sync_at": "2026-10-01T08:00:00Z",
    }
    api(routes={"/v1/me": {**ME, "accounts": [ailing]}})
    [shown] = await accounts.list_accounts()
    assert says in shown["attention"]
    assert shown["last_sync"] == "2026-10-01T08:00:00+00:00"
    assert shown.get("status") == (None if status == "connected" else status)


async def test_an_api_error_keeps_its_message(make_client: Callable) -> None:
    """The server turns it into a ToolError for the model (test_server)."""
    make_client(
        lambda _: httpx.Response(
            401, json={"error": {"code": "unauthorized", "message": "wrong token"}}
        )
    )
    with pytest.raises(ApiError, match="wrong token"):
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


async def test_sharing_is_a_kind_of_its_own(api: Callable) -> None:
    """A token that may share is told so apart from reading."""
    sharer = {**ME["accounts"][0], "operations": [*READ, "share_attachment"]}
    api(routes={"/v1/me": {**ME, "accounts": [sharer]}})
    [shown] = await accounts.list_accounts()
    assert shown["can"] == ["read", "share"]
