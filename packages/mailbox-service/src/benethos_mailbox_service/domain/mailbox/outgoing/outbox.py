"""The outbox: a send put into the account's drafts folder now and handed
to the provider later, at once or at the time asked for. The service
keeps a job that names the draft and a digest of it, never the mail.
The runner in ``runner`` sends what is due."""

from __future__ import annotations

import hashlib
from collections.abc import Awaitable, Callable
from datetime import datetime, timedelta

from benethos_mailbox_common.values import secret

from ....common.clock import utc_now
from ....data.mail import compose
from ....data.models import OutboxJob, OutgoingMessage
from ....data.storage import OutboxRepository
from ....errors import BadRequestError, ConflictError, MailboxServiceError
from ...accounts import NEEDS, drafts
from ...rights import Access
from ..calls import Calls
from . import checks
from .composing import Composer
from .sending import Operation, SendControl

# How far ahead a send may be asked for.
FURTHEST = timedelta(days=30)
# How far in the past a time asked for still counts as now: clocks differ.
SLACK = timedelta(minutes=1)
# How long attempts go on, unless the settings say otherwise.
RETRY_HOURS = 48


def draft_digest(raw: bytes) -> str:
    """What a draft was when queued: a change to it shows in this."""
    return hashlib.sha256(raw).hexdigest()


class Outbox:
    def __init__(
        self,
        calls: Calls,
        composer: Composer,
        sends: SendControl,
        jobs: OutboxRepository,
        clock: Callable[[], datetime] = utc_now,
        retry_hours: int = RETRY_HOURS,
    ) -> None:
        self._calls = calls
        self._composer = composer
        self._sends = sends
        self._jobs = jobs
        self._clock = clock
        self._retry = timedelta(hours=retry_hours)
        # Called once a job is queued: the runner looks again.
        self.wake: Callable[[], None] = lambda: None

    @property
    def jobs(self) -> OutboxRepository:
        return self._jobs

    async def queue_message(
        self,
        access: Access,
        account_id: str,
        message: OutgoingMessage,
        send_at: datetime | None,
    ) -> OutboxJob:
        """Compose the message as for a send, keep it as a draft and queue
        it. The draft holds a reply's reference, so the original is marked
        once it is sent."""
        checks.require(access, "send_message", account_id, message)
        await self._calls.require(account_id, NEEDS["send_draft"])
        now = self._clock()
        due = self._due(send_at, now)
        message = await self._composer.with_sources(access, account_id, message)
        composed = await self._composer.make(access, account_id, message, draft=True)
        recipients = checks.addressed(composed.message.recipients())

        async def place() -> tuple[str, bytes]:
            saved = await self._calls.call(
                account_id, lambda p: drafts(p).save_draft(composed.raw, None)
            )
            draft_id = (await self._calls.published_one(account_id, saved)).id
            # The draft as the provider gives it back: one that renders a
            # draft anew differs from what was composed.
            return draft_id, await self._stored(account_id, draft_id)

        return await self._queue(
            access,
            "send_message",
            account_id,
            recipients,
            composed.message_id,
            (now, due, send_at),
            place,
        )

    async def queue_draft(
        self,
        access: Access,
        account_id: str,
        draft_id: str,
        send_at: datetime | None,
    ) -> OutboxJob:
        """Queue a draft as it is stored. A draft another job waits with is
        a conflict."""
        access.require("send_draft", account_id)
        await self._calls.require(account_id, NEEDS["send_draft"])
        now = self._clock()
        due = self._due(send_at, now)
        if any(
            job.account_id == account_id and job.draft_id == draft_id
            for job in self._jobs.open()
        ):
            raise ConflictError("this draft waits in the outbox already")
        account = self._calls.record(account_id)
        stored = await self._stored(account_id, draft_id)
        out = compose.outgoing(stored, now, compose.new_message_id(account.email))
        recipients = checks.addressed(out.recipients)

        async def place() -> tuple[str, bytes]:
            return draft_id, stored

        return await self._queue(
            access,
            "send_draft",
            account_id,
            recipients,
            out.message_id,
            (now, due, send_at),
            place,
        )

    async def stored(self, account_id: str, draft_id: str) -> bytes:
        """The draft as the provider holds it now."""
        return await self._stored(account_id, draft_id)

    async def _stored(self, account_id: str, draft_id: str) -> bytes:
        return await self._calls.on_message(
            account_id, draft_id, lambda p, native: drafts(p).get_draft(native)
        )

    async def _queue(
        self,
        access: Access,
        operation: Operation,
        account_id: str,
        recipients: list[str],
        message_id: str,
        when: tuple[datetime, datetime, datetime | None],
        place: Callable[[], Awaitable[tuple[str, bytes]]],
    ) -> OutboxJob:
        """Check the grants and record the send as queued, then ``place``
        the draft, then keep the job. A grant that refuses leaves no draft
        behind. ``when`` is now, when it is due and the time asked for."""
        now, due, send_at = when
        job = OutboxJob(
            id=secret.new_id("obx"),
            account_id=account_id,
            user_id=access.user_id,
            credential_id=access.credential_id,
            operation=operation,
            draft_id="",
            digest="",
            message_id_header=message_id,
            recipients=recipients,
            state="queued",
            due_at=due,
            expires_at=due + self._retry,
            send_at=send_at,
            created_at=now,
        )
        await self._sends.queue(
            access, operation, account_id, recipients, message_id, job.id
        )
        try:
            draft_id, stored = await place()
        except MailboxServiceError as exc:
            self._sends.note(job, "failed", exc.code)
            raise
        job = job.model_copy(
            update={"draft_id": draft_id, "digest": draft_digest(stored)}
        )
        self._jobs.add(job)
        self.wake()
        return job

    def _due(self, send_at: datetime | None, now: datetime) -> datetime:
        """When a job asked for ``send_at`` is due: at once without one."""
        if send_at is None:
            return now
        if send_at.tzinfo is None:
            raise BadRequestError("send_at needs a time zone")
        if send_at < now - SLACK:
            raise BadRequestError("send_at lies in the past")
        if send_at > now + FURTHEST:
            raise BadRequestError(f"send_at lies more than {FURTHEST.days} days ahead")
        return max(send_at, now)
