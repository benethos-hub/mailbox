"""The audit of sends, the same for both clients."""

from __future__ import annotations

from collections.abc import Callable
from datetime import UTC, datetime

from benethos_mailbox_client import SendRecord

from ..fake_api import FakeApi

ROW = {
    "id": "snd_1",
    "created_at": "2026-10-09T12:00:00Z",
    "user_id": "usr_1",
    "credential_id": "tok_1",
    "account_id": "acc_1",
    "operation": "send_message",
    "recipients": ["bob@example.org"],
    "outcome": "denied",
    "error": "recipient_not_allowed",
}


async def test_list_sends_of_one_account(make_client: Callable) -> None:
    api = FakeApi({"items": [ROW]})
    found = await make_client(api).list_sends("acc_1", outcome="denied", limit=10)
    assert api.call() == (
        "GET",
        "/v1/accounts/acc_1/sends",
        {"outcome": "denied", "limit": "10"},
        None,
    )
    assert found.items == [
        SendRecord(
            id="snd_1",
            created_at=datetime(2026, 10, 9, 12, tzinfo=UTC),
            user_id="usr_1",
            credential_id="tok_1",
            account_id="acc_1",
            operation="send_message",
            recipients=("bob@example.org",),
            outcome="denied",
            error="recipient_not_allowed",
            refused=(),
            message_id_header=None,
        )
    ]


async def test_list_all_sends_names_the_accounts(make_client: Callable) -> None:
    api = FakeApi({"items": [], "next_cursor": None})
    before = datetime(2026, 10, 9, tzinfo=UTC)
    await make_client(api).list_all_sends(accounts=["acc_1", "acc_2"], before=before)
    [request] = api.seen
    assert request.url.path == "/v1/sends"
    assert request.url.params.get_list("accounts") == ["acc_1", "acc_2"]
    assert request.url.params["before"] == "2026-10-09T00:00:00+00:00"
