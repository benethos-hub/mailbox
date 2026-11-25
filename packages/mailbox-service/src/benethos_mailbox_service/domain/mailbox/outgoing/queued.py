"""Sending a job of the outbox: its draft read and checked, handed to the
provider as an attempt of the job, the draft deleted once it went out
with its copy, and a copy that failed made again later."""

from __future__ import annotations

from dataclasses import dataclass
from datetime import datetime

from ....data.mail import compose
from ....data.models import Account, OutboxJob, SendResult
from ... import changes
from ...accounts import drafts, finds_sent, keeps_sent
from ...rights import Access
from ..calls import Calls
from . import checks
from .delivering import Delivery
from .outbox import draft_digest


@dataclass(frozen=True, slots=True)
class Prepared:
    """A job's draft as it goes out: the bytes, who gets it, the reference
    a reply or forward keeps, the account it goes from, and the digest of
    the draft as it is stored now."""

    account: Account
    raw: bytes
    recipients: list[str]
    reference: str | None
    digest: str


class QueuedSend:
    def __init__(self, calls: Calls, delivery: Delivery) -> None:
        self._calls = calls
        self._delivery = delivery

    async def draft(self, job: OutboxJob) -> bytes:
        """The job's draft as the provider holds it now."""
        return await self._calls.on_message(
            job.account_id, job.draft_id, lambda p, native: drafts(p).get_draft(native)
        )

    async def prepare(self, job: OutboxJob, at: datetime) -> Prepared:
        """The draft read and made ready to go out, dated ``at``, with the
        job's Message-ID. Nothing is recorded: nothing went out."""
        stored = await self.draft(job)
        out = compose.outgoing(stored, at, job.message_id_header)
        return Prepared(
            self._calls.record(job.account_id),
            out.raw,
            checks.addressed(out.recipients),
            out.reference,
            draft_digest(stored),
        )

    async def deliver(
        self, access: Access, job: OutboxJob, prepared: Prepared
    ) -> tuple[SendResult, str | None]:
        """Hand the draft to the provider as an attempt of the job. Once
        it went out, nothing here fails: the draft goes when its copy is
        there, a reply or forward marks its original. Why no copy is in
        the sent folder, None when it is."""
        account = prepared.account
        result, copy_error = await self._delivery.deliver_job(
            access,
            job.operation,
            account,
            prepared.raw,
            prepared.recipients,
            job.message_id_header,
            job.id,
        )
        if copy_error is None:
            with self._delivery.after_sending(
                access, account, "the draft is still there"
            ):
                await self._calls.delete_draft(job.account_id, job.draft_id)
        if prepared.reference is not None:
            with self._delivery.after_sending(
                access, account, "the original is not marked"
            ):
                await self._delivery.mark_from_draft(
                    access, job.account_id, prepared.reference
                )
        return result, copy_error

    async def find_sent(self, job: OutboxJob) -> bool:
        """Whether the sent folder holds the job's message.
        ``NotSupportedError`` where the account cannot look."""
        return await self._calls.call(
            job.account_id, lambda p: finds_sent(p).find_sent(job.message_id_header)
        )

    async def found(self, job: OutboxJob) -> None:
        """The job's message went out after all: its draft goes, and the
        change feed hears of the send."""
        await self._calls.delete_draft(job.account_id, job.draft_id)
        self._calls.changed(changes.MessageSent(job.account_id, job.message_id_header))

    async def keep_copy(self, job: OutboxJob, sent_at: datetime) -> None:
        """The copy in the sent folder made again from the draft, as it
        went out at ``sent_at``, then the draft deleted."""
        out = compose.outgoing(await self.draft(job), sent_at, job.message_id_header)
        await self._calls.call(
            job.account_id, lambda p: keeps_sent(p).keep_sent(out.raw)
        )
        await self._calls.delete_draft(job.account_id, job.draft_id)
