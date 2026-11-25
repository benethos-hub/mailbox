"""The outbox: a send put in, its jobs listed, read and cancelled, the
same for both clients."""

from __future__ import annotations

from collections.abc import Callable
from datetime import UTC, datetime

from benethos_mailbox_client import OutboxEntry

from .api_fake import BODY, FakeApi

JOB = {
    "id": "obx_1",
    "account_id": "acc_1",
    "user_id": "usr_1",
    "operation": "send_message",
    "draft_id": "msg_7",
    "message_id_header": "<m@x>",
    "recipients": ["b@x.example"],
    "state": "queued",
    "attempts": 0,
    "due_at": "2026-11-25T12:00:00Z",
    "expires_at": "2026-11-27T12:00:00Z",
    "send_at": "2026-11-25T12:00:00Z",
    "last_error": None,
    "created_at": "2026-11-25T11:00:00Z",
    "finished_at": None,
}
AT = datetime(2026, 11, 25, 12, tzinfo=UTC)
ENTRY = OutboxEntry(
    id="obx_1",
    account_id="acc_1",
    user_id="usr_1",
    operation="send_message",
    draft_id="msg_7",
    message_id_header="<m@x>",
    recipients=["b@x.example"],
    state="queued",
    attempts=0,
    due_at=AT,
    expires_at=datetime(2026, 11, 27, 12, tzinfo=UTC),
    send_at=AT,
    last_error=None,
    created_at=datetime(2026, 11, 25, 11, tzinfo=UTC),
    finished_at=None,
)


async def test_queue_message(make_client: Callable) -> None:
    api = FakeApi(JOB, status=202)
    found = await make_client(api).queue_message("acc_1", BODY, "key-1", AT)
    body = {**BODY, "outbox": True, "send_at": "2026-11-25T12:00:00+00:00"}
    assert api.call() == ("POST", "/v1/accounts/acc_1/send", {}, body)
    assert api.seen[0].headers["idempotency-key"] == "key-1"
    assert found == ENTRY


async def test_queue_draft(make_client: Callable) -> None:
    api = FakeApi({**JOB, "operation": "send_draft"}, status=202)
    found = await make_client(api).queue_draft("acc_1", "msg_7", "key-2")
    path = "/v1/accounts/acc_1/drafts/msg_7/send"
    assert api.call() == ("POST", path, {}, {"outbox": True})
    assert found.operation == "send_draft"


async def test_list_outbox(make_client: Callable) -> None:
    api = FakeApi({"items": [JOB], "next_cursor": None})
    found = await make_client(api).list_outbox("acc_1", state="queued", limit=5)
    assert api.call() == (
        "GET",
        "/v1/accounts/acc_1/outbox",
        {"state": "queued", "limit": "5"},
        None,
    )
    assert found.items == [ENTRY]


async def test_get_and_cancel_a_job(make_client: Callable) -> None:
    api = FakeApi(JOB)
    assert await make_client(api).get_outbox_job("acc_1", "obx_1") == ENTRY
    assert api.call() == ("GET", "/v1/accounts/acc_1/outbox/obx_1", {}, None)
    ended = {**JOB, "state": "cancelled", "last_error": "cancelled_by_user"}
    api = FakeApi(ended)
    found = await make_client(api).cancel_send("acc_1", "obx_1")
    assert api.call() == ("DELETE", "/v1/accounts/acc_1/outbox/obx_1", {}, None)
    assert (found.state, found.last_error) == ("cancelled", "cancelled_by_user")
