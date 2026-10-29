"""The change feed of one account and of every account, the same for
both clients."""

from __future__ import annotations

from collections.abc import Callable
from datetime import UTC, datetime

from benethos_mailbox_client import Change, Changes

from ..fake_api import FakeApi

AT = datetime(2026, 10, 1, 8, 0, tzinfo=UTC)


async def test_list_changes(make_client: Callable) -> None:
    change = {"type": "message.created", "id": "msg_1", "account_id": "acc_1"}
    at = "2026-10-01T08:00:00+00:00"
    api = FakeApi({"changes": [{**change, "at": at}], "state": "s2", "more": True})
    found = await make_client(api).list_changes("acc_1", since="s1", limit=10)
    assert api.call() == (
        "GET",
        "/v1/accounts/acc_1/changes",
        {"since": "s1", "limit": "10"},
        None,
    )
    assert found == Changes(
        [Change("message.created", "msg_1", "acc_1", AT)], "s2", True
    )


async def test_list_all_changes(make_client: Callable) -> None:
    api = FakeApi({"changes": [], "state": "s1", "more": False})
    found = await make_client(api).list_all_changes(since="s0")
    assert api.call() == ("GET", "/v1/changes", {"since": "s0"}, None)
    assert found == Changes(changes=[], state="s1", more=False)


async def test_list_changes_without_a_point_or_a_limit(make_client: Callable) -> None:
    api = FakeApi({"changes": [], "state": "s0", "more": False})
    await make_client(api).list_changes("acc_1")
    assert api.call() == ("GET", "/v1/accounts/acc_1/changes", {}, None)
