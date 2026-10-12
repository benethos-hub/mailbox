"""Threads of an account, the same for both clients."""

from __future__ import annotations

from collections.abc import Callable
from datetime import UTC, datetime

from benethos_mailbox_client import Address, Thread, ThreadSummary

from ..fake_api import SUMMARY, FakeApi

THREAD = {
    "id": "thr_1",
    "account_id": "acc_1",
    "subject": "Hi",
    "participants": [{"email": "a@example.com", "name": "Ann"}],
    "message_count": 2,
    "unread_count": 1,
    "date": "2026-10-01T08:00:00Z",
    "snippet": "Hello",
    "folder_ids": ["fld_1", "fld_sent"],
    "truncated": False,
}


async def test_list_threads(make_client: Callable) -> None:
    api = FakeApi({"items": [THREAD], "next_cursor": "c2"})
    found = await make_client(api).list_threads("acc_1", folder="inbox", limit=20)
    assert api.call() == (
        "GET",
        "/v1/accounts/acc_1/threads",
        {"folder": "inbox", "limit": "20"},
        None,
    )
    assert found.next_cursor == "c2"
    assert found.items == [
        ThreadSummary(
            id="thr_1",
            account_id="acc_1",
            subject="Hi",
            participants=[Address("a@example.com", "Ann")],
            message_count=2,
            unread_count=1,
            date=datetime(2026, 10, 1, 8, tzinfo=UTC),
            snippet="Hello",
            folder_ids=["fld_1", "fld_sent"],
            truncated=False,
        )
    ]


async def test_get_thread(make_client: Callable) -> None:
    api = FakeApi({**THREAD, "truncated": True, "messages": [SUMMARY]})
    found = await make_client(api).get_thread("acc_1", "thr_1")
    assert api.call() == ("GET", "/v1/accounts/acc_1/threads/thr_1", {}, None)
    assert isinstance(found, Thread)
    assert found.truncated
    assert [m.id for m in found.messages] == ["msg_1"]
    assert found.messages[0].thread_id == "thr_1"
