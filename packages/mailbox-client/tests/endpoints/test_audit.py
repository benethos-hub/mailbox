"""The audit of administration, the same for both clients."""

from __future__ import annotations

from collections.abc import Callable
from datetime import UTC, datetime

from benethos_mailbox_client import Activity

from ..fake_api import FakeApi

ROW = {
    "id": "aud_1",
    "at": "2026-10-09T12:00:00Z",
    "activity": "users.token_revoked",
    "user_id": "usr_1",
    "user_name": "admin",
    "credential": "password",
    "record": "tok_1",
    "source": "127.0.0.1",
    "outcome": "done",
    "detail": "revoked token laptop of desktop",
}


async def test_list_activity(make_client: Callable) -> None:
    api = FakeApi({"items": [ROW], "next_cursor": "c2"})
    since = datetime(2026, 10, 1, tzinfo=UTC)
    found = await make_client(api).list_activity(activity="users", after=since)
    assert api.call() == (
        "GET",
        "/v1/audit",
        {"activity": "users", "after": "2026-10-01T00:00:00+00:00"},
        None,
    )
    assert found.next_cursor == "c2"
    assert found.items == [
        Activity(
            id="aud_1",
            at=datetime(2026, 10, 9, 12, tzinfo=UTC),
            activity="users.token_revoked",
            user_id="usr_1",
            user_name="admin",
            credential="password",
            record="tok_1",
            source="127.0.0.1",
            outcome="done",
            detail="revoked token laptop of desktop",
        )
    ]
