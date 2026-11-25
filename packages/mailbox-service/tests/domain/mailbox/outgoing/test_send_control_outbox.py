"""The audit of sends for the outbox: a queued send, an attempt of a job,
and how a job ended (CONCEPT 7.7)."""

from __future__ import annotations

import asyncio
from datetime import UTC, datetime, timedelta
from pathlib import Path

import pytest

from benethos_mailbox_service.data.models import (
    Account,
    Grant,
    OutboxJob,
    ProviderType,
    SendFilter,
    SentMessage,
)
from benethos_mailbox_service.data.storage import (
    Database,
    InMemorySendLogRepository,
    SqliteAccountRepository,
    SqliteSendLogRepository,
)
from benethos_mailbox_service.domain.mailbox import SendControl
from benethos_mailbox_service.domain.rights.access import Access
from benethos_mailbox_service.errors import RecipientNotAllowedError, SendLimitError

NOW = datetime(2026, 11, 25, 12, tzinfo=UTC)


def sender(**grant: object) -> Access:
    return Access(
        "usr_1",
        "u",
        [Grant.model_validate({"accounts": ["acc_1"], "allow": ["send"], **grant})],
        credential_id="tok_1",
    )


async def sent() -> SentMessage:
    return SentMessage()


def queue(control: SendControl, access: Access, recipients: list[str]) -> None:
    asyncio.run(
        control.queue(access, "send_message", "acc_1", recipients, "<m>", "obx_1")
    )


def test_a_queued_send_is_recorded_with_its_job() -> None:
    store = InMemorySendLogRepository()
    queue(SendControl(store), sender(), ["a@x.example"])
    (record,) = store.list("acc_1", limit=5, before=None)
    assert (record.outcome, record.outbox_job_id) == ("queued", "obx_1")
    assert (record.credential_id, record.message_id_header) == ("tok_1", "<m>")


def test_a_queued_send_does_not_count_against_the_limit() -> None:
    control = SendControl(InMemorySendLogRepository())
    access = sender(max_sends_per_day=1)
    queue(control, access, ["a@x.example"])
    queue(control, access, ["a@x.example"])
    assert control.sent_recently("usr_1", "acc_1") == 0
    asyncio.run(
        control.send(access, "send_message", "acc_1", ["a@x.example"], sent, "<m>")
    )
    with pytest.raises(SendLimitError):
        asyncio.run(
            control.send(access, "send_message", "acc_1", ["a@x.example"], sent, "<n>")
        )


def test_a_recipient_no_grant_allows_is_denied_when_queued() -> None:
    store = InMemorySendLogRepository()
    with pytest.raises(RecipientNotAllowedError):
        queue(SendControl(store), sender(recipients=["*@a.example"]), ["b@b.example"])
    (record,) = store.list("acc_1", limit=5, before=None)
    assert (record.outcome, record.error) == ("denied", "recipient_not_allowed")
    assert record.outbox_job_id == "obx_1"


def test_an_attempt_of_a_job_names_it() -> None:
    store = InMemorySendLogRepository()
    asyncio.run(
        SendControl(store).send(
            sender(), "send_draft", "acc_1", ["a@x.example"], sent, "<m>", "obx_2"
        )
    )
    (record,) = store.list("acc_1", limit=5, before=None)
    assert (record.outcome, record.outbox_job_id) == ("sent", "obx_2")


def job() -> OutboxJob:
    return OutboxJob(
        id="obx_3",
        account_id="acc_1",
        user_id="usr_1",
        credential_id="tok_1",
        operation="send_draft",
        draft_id="msg_1",
        digest="0" * 64,
        message_id_header="<m>",
        recipients=["a@x.example"],
        state="unknown",
        due_at=NOW,
        expires_at=NOW + timedelta(hours=48),
        created_at=NOW,
    )


def test_the_end_of_a_job_is_recorded(tmp_path: Path) -> None:
    db = Database(tmp_path / "sends.db")
    SqliteAccountRepository(db).add(
        Account(id="acc_1", provider=ProviderType.IMAP, email="a@example.org")
    )
    store = SqliteSendLogRepository(db)
    control = SendControl(store)
    control.note(job(), "unknown", "provider_unavailable")
    control.note(job(), "cancelled", "draft_changed")
    found = store.list("acc_1", limit=5, before=None)
    assert sorted((r.outcome, r.error, r.outbox_job_id) for r in found) == [
        ("cancelled", "draft_changed", "obx_3"),
        ("unknown", "provider_unavailable", "obx_3"),
    ]
    assert (
        store.list(
            "acc_1", limit=5, before=None, matching=SendFilter(outcome="unknown")
        )[0].user_id
        == "usr_1"
    )
    db.close()
