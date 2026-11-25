"""The outbox, putting a send in: a draft kept at the provider, a job that
names it and its digest, nothing sent yet."""

from __future__ import annotations

import asyncio
from datetime import UTC, datetime, timedelta

import pytest

from benethos_mailbox_service.assembly import Services
from benethos_mailbox_service.data.models import (
    DraftMessage,
    Grant,
    OutboxJob,
    OutgoingMessage,
    Recipient,
)
from benethos_mailbox_service.domain.mailbox.outgoing.outbox import draft_digest
from benethos_mailbox_service.domain.rights import Access
from benethos_mailbox_service.errors import (
    BadRequestError,
    ConflictError,
    NotSupportedError,
    RecipientNotAllowedError,
)

from ....conftest import ADMIN, memory_of


def message(to: str = "bob@example.com") -> OutgoingMessage:
    return OutgoingMessage(to=[Recipient(email=to)], subject="Plan", text="Ready.")


def queue(
    services: Services,
    account_id: str,
    send_at: datetime | None = None,
    access: Access = ADMIN,
    to: str = "bob@example.com",
    key: str | None = None,
) -> OutboxJob:
    return asyncio.run(
        services.mailbox.outgoing.queue_message(
            access, account_id, message(to), send_at, key
        )
    )


def drafts(services: Services, account_id: str) -> list[str]:
    page = asyncio.run(
        services.mailbox.outgoing.list_drafts(ADMIN, account_id, limit=10, cursor=None)
    )
    return [item.id for item in page.items]


def stored(services: Services, account_id: str, draft_id: str) -> bytes:
    return asyncio.run(services.mailbox.outgoing.outbox.stored(account_id, draft_id))


def test_a_queued_message_waits_as_a_draft(services: Services, account_id: str) -> None:
    job = queue(services, account_id)
    assert job.state == "queued" and job.attempts == 0
    assert drafts(services, account_id) == [job.draft_id]
    assert job.digest == draft_digest(stored(services, account_id, job.draft_id))
    assert job.message_id_header.encode() in stored(services, account_id, job.draft_id)
    assert job.recipients == ["bob@example.com"]
    assert job.due_at == job.created_at and job.send_at is None
    assert job.expires_at - job.due_at == timedelta(hours=48)
    # Nothing went out yet.
    assert memory_of(services, account_id).outbox == []
    assert services.mailbox.outgoing.outbox.jobs.get(job.id) == job
    (record,) = services.mailbox.outgoing.list_sends(
        ADMIN, account_id, limit=5, cursor=None
    ).items
    assert (record.outcome, record.outbox_job_id) == ("queued", job.id)


def test_a_send_at_sets_when_it_is_due(services: Services, account_id: str) -> None:
    later = datetime.now(UTC) + timedelta(days=2)
    job = queue(services, account_id, later)
    assert job.due_at == later == job.send_at
    assert job.expires_at == later + timedelta(hours=48)


@pytest.mark.parametrize(
    "send_at",
    [
        datetime.now(UTC) - timedelta(minutes=5),
        datetime.now(UTC) + timedelta(days=31),
        datetime(2030, 1, 1, 12),
    ],
    ids=["past", "too far", "no time zone"],
)
def test_a_send_at_out_of_bounds_is_refused(
    services: Services, account_id: str, send_at: datetime
) -> None:
    with pytest.raises(BadRequestError):
        queue(services, account_id, send_at)
    assert drafts(services, account_id) == []


def test_a_recipient_no_grant_allows_leaves_no_draft(
    services: Services, account_id: str
) -> None:
    limited = Access(
        "usr_1",
        "u",
        [Grant(accounts=[account_id], allow=["send"], recipients=["*@a.example"])],
    )
    with pytest.raises(RecipientNotAllowedError):
        queue(services, account_id, access=limited, to="bob@b.example")
    assert drafts(services, account_id) == []
    assert services.mailbox.outgoing.outbox.jobs.open() == []


def test_a_draft_is_queued_once(services: Services, account_id: str) -> None:
    outgoing = services.mailbox.outgoing
    draft = asyncio.run(
        outgoing.create_draft(
            ADMIN,
            account_id,
            DraftMessage(to=[Recipient(email="bob@example.com")], text="Hi."),
        )
    )
    job = asyncio.run(outgoing.queue_draft(ADMIN, account_id, draft.id))
    assert (job.operation, job.draft_id) == ("send_draft", draft.id)
    assert job.digest == draft_digest(stored(services, account_id, draft.id))
    with pytest.raises(ConflictError):
        asyncio.run(outgoing.queue_draft(ADMIN, account_id, draft.id))


def test_a_draft_without_recipients_is_refused(
    services: Services, account_id: str
) -> None:
    outgoing = services.mailbox.outgoing
    draft = asyncio.run(
        outgoing.create_draft(ADMIN, account_id, DraftMessage(text="Hi."))
    )
    with pytest.raises(BadRequestError):
        asyncio.run(outgoing.queue_draft(ADMIN, account_id, draft.id))


def test_the_same_key_gives_the_same_job(services: Services, account_id: str) -> None:
    first = queue(services, account_id, key="k1")
    again = queue(services, account_id, key="k1")
    assert again == first
    assert drafts(services, account_id) == [first.draft_id]


def test_an_account_without_drafts_has_no_outbox(
    pop3_services: Services, pop3_account_id: str
) -> None:
    with pytest.raises(NotSupportedError):
        queue(pop3_services, pop3_account_id)
