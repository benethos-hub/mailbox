"""The runner of the outbox: in rounds a few seconds apart it sends what
is due, one job per account at a time, the earliest due first.

A job is sent with the rights of the user who queued it, read anew for
each attempt: a right taken away, a token revoked or a user gone ends
it. A draft deleted or changed in a mail client since cancels it: only
what was queued goes out. A server that is away or busy, a refused
sign-in and a reached send limit wait for the next attempt, until the
job's time is up. Any other refusal ends it. A job sent whose copy in
the sent folder failed keeps its draft until the copy is made again."""

from __future__ import annotations

from collections.abc import Awaitable, Callable
from datetime import datetime, timedelta

import anyio

from ....common.clock import utc_now
from ....data.models import OutboxJob, OutboxState, SendOutcome
from ....errors import (
    MailboxServiceError,
    NotFoundError,
    NotSupportedError,
    OutcomeUnknownError,
    ProviderAuthError,
    ProviderUnavailableError,
    SendLimitError,
)
from ...activity import OUTBOX, ActivityLog
from ...activity import mailbox as said
from ...rights import Access
from ...rounds import rounds
from .outbox import Outbox
from .queued import Prepared, QueuedSend
from .sending import SendControl

# Seconds between two rounds.
POLL = 5.0
# Seconds to the next attempt after the first, second, ... failed one.
STEPS = (60, 120, 300, 900)
# Seconds between attempts after those, and while a sign-in is refused.
LATER = 1800
# How long an unclear attempt waits before the sent folder is looked into
# again: a provider files its copy a while after it took the message.
UNCLEAR = timedelta(minutes=15)
# The codes of a job whose draft was deleted or changed after it was queued.
DRAFT_GONE = "draft_gone"
DRAFT_CHANGED = "draft_changed"
# The code of a job whose time was up before it could be tried.
EXPIRED = "expired"
# The code of a job whose sent copy could not be made.
NO_COPY = "no_sent_copy"
# How the end of a job stands in the audit of sends.
NOTED: dict[OutboxState, SendOutcome] = {
    "failed": "failed",
    "cancelled": "cancelled",
    "unknown": "unknown",
}

AccessFor = Callable[[OutboxJob], Access | None]
Sleep = Callable[[float], Awaitable[None]]


class OutboxRunner:
    def __init__(
        self,
        outbox: Outbox,
        queued: QueuedSend,
        sends: SendControl,
        access_for: AccessFor,
        clock: Callable[[], datetime] = utc_now,
        sleep: Sleep = anyio.sleep,
        activity: ActivityLog | None = None,
        purge: Callable[[], None] = lambda: None,
    ) -> None:
        """``access_for`` gives what the user who queued a job may do now,
        None when that user or its token is gone. ``purge`` removes the
        ended jobs that are due to go, called each round."""
        self._jobs = outbox.jobs
        self._queued = queued
        self._sends = sends
        self._access_for = access_for
        self._clock = clock
        self._sleep = sleep
        self._activity = activity or ActivityLog(clock)
        self._purge = purge

    async def run(self) -> None:
        """Until cancelled. A failure ends a round, never the runner."""
        await self.recover()
        await rounds(
            self.send_due,
            pause=POLL,
            sleep=self._sleep,
            activity=self._activity,
            by=OUTBOX,
        )

    async def recover(self) -> None:
        """A job still sending when the service stopped may have gone out
        or not: its outcome is looked into as any unclear one."""
        now = self._clock()
        for job in self._jobs.open():
            if job.state == "sending":
                await self._unclear(job, "interrupted", now)

    async def send_due(self) -> None:
        """One round: per account the earliest job, if it is due."""
        self._purge()
        now = self._clock()
        seen: set[str] = set()
        for job in self._jobs.open():
            if job.account_id in seen:
                continue
            seen.add(job.account_id)
            if job.due_at > now:
                continue
            if job.state == "copying":
                await self._copy(job, now)
            elif job.state == "queued" and now > job.expires_at:
                # The service was away past the job's time: not sent late.
                self._end(job, "failed", EXPIRED, note=True)
            elif job.state == "queued":
                await self._attempt(job, now)

    async def _attempt(self, job: OutboxJob, now: datetime) -> None:
        access = self._access_for(job)
        if access is None:
            self._end(job, "failed", "forbidden", note=True)
            return
        taken = job.model_copy(
            update={"state": "sending", "attempts": job.attempts + 1}
        )
        if not self._jobs.update(taken, was="queued"):
            return
        if taken.unclear_since is not None:
            if not await self._looked(taken, now):
                return
            taken = taken.model_copy(update={"unclear_since": None})
        prepared = await self._prepared(taken, now)
        if prepared is None:
            return
        try:
            _, copy_error = await self._queued.deliver(access, taken, prepared)
        except OutcomeUnknownError as exc:
            await self._unclear(taken, exc.code, now)
        except MailboxServiceError as exc:
            self._refused(taken, exc, now)
        except Exception:
            # A fault of the service itself: whether it went out is not
            # known, so it is not sent again.
            self._end(taken, "unknown", "internal_error", note=True)
            raise
        else:
            self._went_out(taken, copy_error, now)

    async def _prepared(self, job: OutboxJob, now: datetime) -> Prepared | None:
        """The job's draft made ready to go out, None when the job ended:
        a draft deleted or changed in a mail client cancels it."""
        try:
            prepared = await self._queued.prepare(job, now)
        except NotFoundError:
            self._end(job, "cancelled", DRAFT_GONE, note=True)
            return None
        except MailboxServiceError as exc:
            self._end(job, "failed", exc.code, note=True)
            return None
        if prepared.digest != job.digest:
            # What goes out is only what was queued.
            self._end(job, "cancelled", DRAFT_CHANGED, note=True)
            return None
        return prepared

    async def _unclear(self, job: OutboxJob, code: str, now: datetime) -> None:
        """An attempt whose outcome cannot be told. Found in the sent folder,
        it went out. An account that cannot look ends it as unknown: it is
        never sent twice. Else it is looked for again after a while, and
        sent anew only when it is not there then."""
        found = await self._find(job)
        if found is None:
            self._end(job, "unknown", code, note=True)
        elif found:
            await self._was_sent(job, job.unclear_since or now)
        else:
            self._stored(
                job.model_copy(
                    update={
                        "state": "queued",
                        "unclear_since": job.unclear_since or now,
                        "due_at": now + UNCLEAR,
                        "last_error": code,
                    }
                ),
                was=job.state,
            )
            self._waits(job, code, int(UNCLEAR.total_seconds()))

    async def _looked(self, job: OutboxJob, now: datetime) -> bool:
        """For a job with an unclear attempt: whether it may be sent now,
        because the sent folder still does not hold it."""
        found = await self._find(job)
        if found is None:
            self._end(job, "unknown", job.last_error, note=True)
            return False
        if found:
            await self._was_sent(job, job.unclear_since or now)
            return False
        return True

    async def _find(self, job: OutboxJob) -> bool | None:
        """Whether the sent folder holds the job's message, None where the
        account cannot look. A failure to look counts as not found yet."""
        try:
            return await self._queued.find_sent(job)
        except NotSupportedError:
            return None
        except MailboxServiceError:
            return False

    async def _was_sent(self, job: OutboxJob, at: datetime) -> None:
        """The job's message went out after all."""
        await self._queued.found(job)
        self._sends.note(job, "sent", None)
        self._end(job, "sent", None, at=at)

    def _refused(self, job: OutboxJob, exc: MailboxServiceError, now: datetime) -> None:
        """An attempt that did not send, as the audit of sends has it."""
        if isinstance(exc, SendLimitError):
            self._again(job, exc.code, now, exc.retry_after)
        elif isinstance(exc, ProviderAuthError):
            self._again(job, exc.code, now, LATER)
        elif isinstance(exc, ProviderUnavailableError):
            self._again(job, exc.code, now)
        else:
            self._end(job, "failed", exc.code)

    def _went_out(self, job: OutboxJob, copy_error: str | None, now: datetime) -> None:
        if copy_error is None:
            self._end(job, "sent", None, at=now)
            return
        self._stored(
            job.model_copy(
                update={
                    "state": "copying",
                    "finished_at": now,
                    "due_at": now + timedelta(seconds=STEPS[0]),
                    "last_error": NO_COPY,
                }
            ),
            was="sending",
        )

    async def _copy(self, job: OutboxJob, now: datetime) -> None:
        sent_at = job.finished_at or now
        try:
            await self._queued.keep_copy(job, sent_at)
        except NotSupportedError:
            self._end(job, "sent", NO_COPY, at=sent_at, was="copying", told=True)
        except MailboxServiceError as exc:
            due = now + timedelta(seconds=self._step(job.attempts))
            if due > job.expires_at:
                self._end(job, "sent", NO_COPY, at=sent_at, was="copying", told=True)
                return
            self._stored(
                job.model_copy(
                    update={
                        "due_at": due,
                        "attempts": job.attempts + 1,
                        "last_error": exc.code,
                    }
                ),
                was="copying",
            )
        else:
            self._end(job, "sent", None, at=sent_at, was="copying")

    def _again(
        self, job: OutboxJob, code: str, now: datetime, seconds: int | None = None
    ) -> None:
        """The job waits for its next attempt, unless its time is up."""
        wait = seconds if seconds is not None else self._step(job.attempts)
        due = now + timedelta(seconds=wait)
        if due > job.expires_at:
            self._end(job, "failed", code, note=True)
            return
        self._stored(
            job.model_copy(
                update={"state": "queued", "due_at": due, "last_error": code}
            ),
            was="sending",
        )
        self._waits(job, code, wait)

    def _waits(self, job: OutboxJob, code: str, wait: int) -> None:
        self._activity.record(
            said.OutboxRetry(
                by=OUTBOX,
                account_id=job.account_id,
                job_id=job.id,
                code=code,
                seconds=wait,
            )
        )

    @staticmethod
    def _step(attempts: int) -> int:
        """Seconds to the next attempt after ``attempts`` failed ones."""
        return STEPS[attempts - 1] if 0 < attempts <= len(STEPS) else LATER

    def _end(
        self,
        job: OutboxJob,
        state: OutboxState,
        code: str | None,
        *,
        at: datetime | None = None,
        was: OutboxState | None = None,
        note: bool = False,
        told: bool = False,
    ) -> None:
        """The job ends in ``state``. ``note`` records it in the audit of
        sends, where no attempt says so. Every end but a plain send is in
        the log, as is a send without its copy (``told``)."""
        ended = job.model_copy(
            update={
                "state": state,
                "last_error": code,
                "finished_at": at or self._clock(),
            }
        )
        if not self._stored(ended, was=was or job.state):
            return
        if note and state in NOTED:
            self._sends.note(ended, NOTED[state], code)
        self._queued.ended(ended)
        if state != "sent" or told:
            self._activity.record(
                said.OutboxEnded(
                    by=OUTBOX,
                    account_id=job.account_id,
                    job_id=job.id,
                    state=state,
                    code=code or "",
                )
            )

    def _stored(self, job: OutboxJob, *, was: OutboxState) -> bool:
        return self._jobs.update(job, was=was)
