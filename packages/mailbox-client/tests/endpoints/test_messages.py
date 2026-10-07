"""Messages: the lists, one message, changes, flags and moves, deleting,
the same for both clients."""

from __future__ import annotations

from collections.abc import Callable

import pytest

from benethos_mailbox_client import Changes, Outcome, Page

from ..fake_api import PAGE, FakeApi


async def test_list_messages(make_client: Callable) -> None:
    api = FakeApi(PAGE)
    found = await make_client(api).list_messages(
        "acc_1", folder="inbox", text="hi", sender="a@x.org", unread=True, limit=5
    )
    assert api.call() == (
        "GET",
        "/v1/accounts/acc_1/messages",
        {
            "folder": "inbox",
            "q": "hi",
            "from": "a@x.org",
            "unread": "true",
            "limit": "5",
        },
        None,
    )
    assert found == Page([{"id": "msg_1"}], "c2", ["acc_2: timed out"])


async def test_list_messages_of_every_account(make_client: Callable) -> None:
    api = FakeApi({"items": []})
    found = await make_client(api).list_messages(None, limit=5, cursor="c")
    assert api.call() == ("GET", "/v1/messages", {"limit": "5", "cursor": "c"}, None)
    assert found == Page([], None)


async def test_list_changes(make_client: Callable) -> None:
    change = {"type": "message.created", "id": "msg_1", "account_id": "acc_1"}
    api = FakeApi({"changes": [{**change, "at": "t"}], "state": "s2", "more": True})
    found = await make_client(api).list_changes(None, since="s1", limit=10)
    assert api.call() == ("GET", "/v1/changes", {"since": "s1", "limit": "10"}, None)
    assert found == Changes([{**change, "at": "t"}], "s2", True)


async def test_get_message(make_client: Callable) -> None:
    api = FakeApi({"id": "msg_1"})
    assert await make_client(api).get_message("acc_1", "msg_1") == {"id": "msg_1"}
    assert api.call() == ("GET", "/v1/accounts/acc_1/messages/msg_1", {}, None)


async def test_update_messages(make_client: Callable) -> None:
    results = [{"id": "m1", "ok": True}, {"id": "m2", "ok": False}]
    results.append({"id": "m3", "error": {"message": "gone"}})
    api = FakeApi({"results": results})
    found = await make_client(api).update_messages(
        "acc_1", ["m1", "m2", "m3"], unread=False, folder_id="archive"
    )
    assert api.call() == (
        "POST",
        "/v1/accounts/acc_1/messages/batch",
        {},
        {
            "ids": ["m1", "m2", "m3"],
            "action": "update",
            "changes": {"unread": False, "folder_ids": ["archive"]},
        },
    )
    assert found == Outcome(
        ["m1"], [{"id": "m2", "error": "failed"}, {"id": "m3", "error": "gone"}]
    )


async def test_trash_messages(make_client: Callable) -> None:
    api = FakeApi({"results": [{"id": "m1", "ok": True}]})
    found = await make_client(api).trash_messages("acc_1", ["m1"])
    body = {"ids": ["m1"], "action": "delete"}
    assert api.call() == ("POST", "/v1/accounts/acc_1/messages/batch", {}, body)
    assert found.done == ["m1"]


@pytest.mark.parametrize(
    ("permanent", "query"), [(False, {}), (True, {"permanent": "true"})]
)
async def test_delete_message(
    make_client: Callable, permanent: bool, query: dict[str, str]
) -> None:
    api = FakeApi(None)
    client = make_client(api)
    assert await client.delete_message("acc_1", "msg_1", permanent=permanent) is None
    assert api.call() == ("DELETE", "/v1/accounts/acc_1/messages/msg_1", query, None)
