"""The outbox in the send tools: a send queued answers that it is not
sent yet, with its job; the outbox listed and a send cancelled."""

from __future__ import annotations

from collections.abc import Callable
from datetime import UTC, datetime

from benethos_mailbox_mcp.tools import sending

JOB = {
    "id": "obx_1",
    "account_id": "acc_1",
    "user_id": "usr_1",
    "operation": "send_message",
    "draft_id": "msg_d",
    "message_id_header": "<m1@example.com>",
    "recipients": ["bob@example.com"],
    "state": "queued",
    "attempts": 0,
    "due_at": "2026-11-26T08:00:00+00:00",
    "expires_at": "2026-11-28T08:00:00+00:00",
    "send_at": "2026-11-26T08:00:00+00:00",
    "last_error": None,
    "created_at": "2026-11-25T12:00:00+00:00",
    "finished_at": None,
}
AT = datetime(2026, 11, 26, 8, tzinfo=UTC)


async def test_a_queued_mail_is_not_sent_yet(api: Callable) -> None:
    handler = api(JOB)
    result = await sending.send_message(
        "acc_1", to=["bob@example.com"], text="Hello", send_at=AT
    )
    assert result["sent"] is False and result["queued"] is True
    assert (result["job_id"], result["state"]) == ("obx_1", "queued")
    assert result["send_at"] == "2026-11-26T08:00:00+00:00"
    assert "background" in result["note"]
    [call] = handler.calls
    assert call.path == "/v1/accounts/acc_1/send"
    assert call.body["outbox"] is True
    assert call.body["send_at"] == "2026-11-26T08:00:00+00:00"


async def test_a_queued_call_has_a_key_of_its_own(api: Callable) -> None:
    handler = api(JOB)
    await sending.send_message("acc_1", to=["bob@example.com"], text="Hi", outbox=True)
    await sending.send_message("acc_1", to=["bob@example.com"], text="Hi", outbox=True)
    await sending.send_message("acc_1", to=["bob@example.com"], text="Hi", send_at=AT)
    keys = handler.keys
    assert keys[0] == keys[1] != keys[2]


async def test_a_draft_goes_into_the_outbox(api: Callable) -> None:
    handler = api({**JOB, "operation": "send_draft"})
    result = await sending.send_draft("acc_1", "msg_d", outbox=True)
    assert result["queued"] is True
    [call] = handler.calls
    assert call.path == "/v1/accounts/acc_1/drafts/msg_d/send"
    assert call.body == {"outbox": True}


async def test_the_outbox_and_a_send_cancelled(api: Callable) -> None:
    failed = {**JOB, "state": "failed", "last_error": "provider_unavailable"}
    handler = api({"items": [failed], "next_cursor": None})
    listed = await sending.list_outbox("acc_1", state="failed")
    assert listed["jobs"][0]["last_error"] == "provider_unavailable"
    assert "unknown" in listed["note"]
    assert handler.calls[0].path == "/v1/accounts/acc_1/outbox"
    api({**JOB, "state": "cancelled", "last_error": "cancelled_by_user"})
    cancelled = await sending.cancel_send("acc_1", "obx_1")
    assert (cancelled["job_id"], cancelled["state"]) == ("obx_1", "cancelled")
