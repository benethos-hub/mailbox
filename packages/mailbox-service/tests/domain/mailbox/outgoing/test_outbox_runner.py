"""The runner of the outbox: what is due goes out once, with the rights of
the user who queued it; a server away waits, a refusal ends the job, a
missing sent copy is made again."""

from __future__ import annotations

import asyncio
from datetime import timedelta
from email import message_from_bytes

import pytest

from benethos_mailbox_service.data.models import (
    DraftMessage,
    Message,
    ProviderType,
    Recipient,
    SentMessage,
)
from benethos_mailbox_service.errors import BadRequestError, ProviderUnavailableError

from ....conftest import ADMIN, create_account
from .outbox_helpers import Outbox, build


@pytest.fixture
def box(messages: list[Message]) -> Outbox:
    return build(messages)


def test_a_due_job_goes_out_once_and_its_draft_goes(box: Outbox) -> None:
    job = box.queue()
    box.round()
    [raw] = box.sent()
    assert message_from_bytes(raw)["Message-ID"] == job.message_id_header
    done = box.job(job.id)
    assert (done.state, done.attempts, done.finished_at) == ("sent", 1, box.clock.now)
    assert box.drafts() == []
    assert box.outcomes() == [("queued", None), ("sent", None)]
    box.round()
    assert len(box.sent()) == 1


def test_a_job_waits_for_its_time(box: Outbox) -> None:
    job = box.queue(hours=1)
    box.round()
    assert box.sent() == [] and box.job(job.id).state == "queued"
    box.clock.tick(hours=1)
    box.round()
    assert box.job(job.id).state == "sent"


def test_a_server_away_is_tried_again_later(box: Outbox) -> None:
    box.failing(ProviderUnavailableError("away"))
    job = box.queue()
    box.round()
    waiting = box.job(job.id)
    assert (waiting.state, waiting.attempts) == ("queued", 1)
    assert waiting.last_error == "provider_unavailable"
    assert waiting.due_at == box.clock.now + timedelta(seconds=60)
    box.round()
    assert box.sent() == []
    box.clock.tick(seconds=60)
    box.round()
    assert box.job(job.id).state == "sent" and len(box.sent()) == 1


def test_a_refusal_ends_the_job_and_keeps_the_draft(box: Outbox) -> None:
    box.failing(BadRequestError("no"))
    job = box.queue()
    box.round()
    failed = box.job(job.id)
    assert (failed.state, failed.last_error) == ("failed", "bad_request")
    assert box.drafts() == [job.draft_id]
    assert box.outcomes() == [("failed", "bad_request"), ("queued", None)]


def test_attempts_end_when_the_time_is_up(messages: list[Message]) -> None:
    box = build(messages, hours=1)
    box.failing(*[ProviderUnavailableError("away")] * 20)
    job = box.queue()
    for _ in range(20):
        now = box.job(job.id)
        if not now.open:
            break
        box.clock.now = max(box.clock.now, now.due_at)
        box.round()
    ended = box.job(job.id)
    assert (ended.state, ended.last_error) == ("failed", "provider_unavailable")
    assert ended.attempts == 6
    assert box.drafts() == [job.draft_id]
    assert box.sent() == []


def test_a_missing_sent_copy_is_made_again(box: Outbox) -> None:
    provider = box.memory()

    async def send(raw: bytes, sender: str, recipients: list[str]) -> SentMessage:
        provider.outbox.append((sender, recipients, raw))
        return SentMessage(copy_error="the sent folder refused")

    provider.send = send  # type: ignore[method-assign]
    job = box.queue()
    box.round()
    copying = box.job(job.id)
    assert copying.state == "copying" and copying.finished_at == box.clock.now
    assert box.drafts() == [job.draft_id]
    box.clock.tick(seconds=60)
    box.round()
    assert box.job(job.id).state == "sent"
    assert box.drafts() == []
    copies = [
        m for m in provider.messages if m.message_id_header == job.message_id_header
    ]
    assert len(copies) == 1 and len(box.sent()) == 1


def test_a_user_gone_ends_the_job_unsent(box: Outbox) -> None:
    job = box.queue()
    box.services.users.delete_user(ADMIN, box.user_id)
    box.round()
    ended = box.job(job.id)
    assert (ended.state, ended.last_error) == ("failed", "forbidden")
    assert box.sent() == []
    assert box.outcomes() == [("failed", "forbidden"), ("queued", None)]


def test_one_job_per_account_at_a_time(box: Outbox) -> None:
    other = create_account(
        box.services.accounts, ProviderType.MEMORY, "other@example.com"
    ).id
    first = box.queue()
    box.clock.tick(seconds=1)
    second = box.queue()
    elsewhere = box.queue(other)
    box.round()
    assert box.job(first.id).state == "sent"
    assert box.job(second.id).state == "queued"
    assert box.job(elsewhere.id).state == "sent"
    box.round()
    assert box.job(second.id).state == "sent"


def test_a_draft_deleted_since_cancels_the_job(box: Outbox) -> None:
    job = box.queue()
    asyncio.run(
        box.services.mailbox.outgoing.delete_draft(ADMIN, box.account_id, job.draft_id)
    )
    box.round()
    ended = box.job(job.id)
    assert (ended.state, ended.last_error) == ("cancelled", "draft_gone")
    assert box.sent() == []
    assert ("cancelled", "draft_gone") in box.outcomes()


def test_a_draft_changed_since_cancels_the_job_and_stays(box: Outbox) -> None:
    job = box.queue()
    asyncio.run(
        box.services.mailbox.outgoing.update_draft(
            ADMIN,
            box.account_id,
            job.draft_id,
            DraftMessage(to=[Recipient(email="eve@example.com")], text="Other."),
        )
    )
    (changed,) = box.drafts()
    box.round()
    ended = box.job(job.id)
    assert (ended.state, ended.last_error) == ("cancelled", "draft_changed")
    assert box.sent() == []
    assert box.drafts() == [changed]


def events(box: Outbox) -> list[tuple[str, str]]:
    found = box.services.changes.after([box.account_id], 0, limit=50)
    return [
        (e.record.type, e.record.id)
        for e in found
        if e.record.type.startswith("message.sen")
    ]


def test_each_end_without_a_send_is_an_event(box: Outbox) -> None:
    box.failing(BadRequestError("no"))
    refused = box.queue()
    box.round()
    gone = box.queue()
    asyncio.run(
        box.services.mailbox.outgoing.delete_draft(ADMIN, box.account_id, gone.draft_id)
    )
    box.round()
    box.queue()
    box.round()
    found = events(box)
    assert found[:2] == [
        ("message.send_failed", refused.id),
        ("message.send_cancelled", gone.id),
    ]
    assert [kind for kind, _ in found[2:]] == ["message.sent"]
