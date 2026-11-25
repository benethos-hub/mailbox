"""The runner of the outbox: what is due goes out once, with the rights of
the user who queued it; a server away waits, a refusal ends the job, a
missing sent copy is made again."""

from __future__ import annotations

import asyncio
from collections.abc import Awaitable, Callable
from dataclasses import dataclass
from datetime import timedelta
from email import message_from_bytes

import pytest

from benethos_mailbox_service.assembly import Services, build_services
from benethos_mailbox_service.config import Settings
from benethos_mailbox_service.data.models import (
    Message,
    OutboxJob,
    OutgoingMessage,
    ProviderType,
    Recipient,
    SentMessage,
)
from benethos_mailbox_service.data.providers import (
    CredentialReader,
    ProviderSettings,
    Reads,
    build_provider,
)
from benethos_mailbox_service.data.providers.memory import MemoryProvider
from benethos_mailbox_service.domain.mailbox import OutboxRunner
from benethos_mailbox_service.domain.rights import Access, permissions
from benethos_mailbox_service.errors import (
    BadRequestError,
    MailboxServiceError,
    ProviderUnavailableError,
)

from ....clocks import Clock
from ....conftest import ADMIN, CHEAP, create_account, memory_of

Send = Callable[[bytes, str, list[str]], Awaitable[SentMessage]]


@dataclass
class Outbox:
    services: Services
    clock: Clock
    account_id: str
    access: Access
    user_id: str

    @property
    def runner(self) -> OutboxRunner:
        assert self.services.outbox is not None
        return self.services.outbox

    def queue(self, account_id: str | None = None, **when: float) -> OutboxJob:
        send_at = self.clock.now + timedelta(**when) if when else None
        return asyncio.run(
            self.services.mailbox.outgoing.queue_message(
                self.access,
                account_id or self.account_id,
                OutgoingMessage(to=[Recipient(email="bob@example.com")], text="Hi."),
                send_at,
            )
        )

    def round(self) -> None:
        asyncio.run(self.runner.send_due())

    def job(self, job_id: str) -> OutboxJob:
        return self.services.mailbox.outgoing.outbox.jobs.get(job_id)

    def sent(self, account_id: str | None = None) -> list[bytes]:
        return [raw for _, _, raw in self.memory(account_id).outbox]

    def memory(self, account_id: str | None = None) -> MemoryProvider:
        return memory_of(self.services, account_id or self.account_id)

    def drafts(self) -> list[str]:
        page = asyncio.run(
            self.services.mailbox.outgoing.list_drafts(
                ADMIN, self.account_id, limit=10, cursor=None
            )
        )
        return [item.id for item in page.items]

    def outcomes(self) -> list[tuple[str, str | None]]:
        page = self.services.mailbox.outgoing.list_sends(
            ADMIN, self.account_id, limit=20, cursor=None
        )
        return sorted((r.outcome, r.error) for r in page.items)

    def failing(self, *errors: MailboxServiceError | None) -> None:
        """The provider's sends raise ``errors`` in turn, then send."""
        provider = self.memory()
        real: Send = provider.send
        left = list(errors)

        async def send(raw: bytes, sender: str, recipients: list[str]) -> SentMessage:
            error = left.pop(0) if left else None
            if error is not None:
                raise error
            return await real(raw, sender, recipients)

        provider.send = send  # type: ignore[method-assign]


def build(messages: list[Message], hours: int = 48) -> Outbox:
    clock = Clock()

    def factory(
        kind: ProviderType, settings: ProviderSettings, credentials: CredentialReader
    ) -> Reads:
        if kind is ProviderType.MEMORY:
            return MemoryProvider(messages=list(messages))
        return build_provider(kind, settings, credentials)

    services = build_services(
        Settings(storage="memory", outbox_retry_hours=hours),
        provider_factory=factory,
        password_hasher=CHEAP,
        clock=clock,
    )
    account = create_account(services.accounts, ProviderType.MEMORY, "me@example.com")
    user = services.users.create_user(
        ADMIN, "sender", [], [], service=[permissions.ADMIN]
    )
    access = services.auth.access_of(user.id)
    assert access is not None
    return Outbox(services, clock, account.id, access, user.id)


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
    first, second = box.queue(), box.queue()
    elsewhere = box.queue(other)
    box.round()
    assert box.job(first.id).state == "sent"
    assert box.job(second.id).state == "queued"
    assert box.job(elsewhere.id).state == "sent"
    box.round()
    assert box.job(second.id).state == "sent"


def test_a_job_sending_when_the_service_stopped_is_unknown(box: Outbox) -> None:
    job = box.queue()
    jobs = box.services.mailbox.outgoing.outbox.jobs
    jobs.update(job.model_copy(update={"state": "sending"}), was="queued")
    box.runner.recover()
    ended = box.job(job.id)
    assert (ended.state, ended.last_error) == ("unknown", "interrupted")
    assert box.outcomes() == [("queued", None), ("unknown", "interrupted")]
    box.round()
    assert box.sent() == []
