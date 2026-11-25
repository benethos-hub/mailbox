"""The jobs of the outbox as callers see them: listed, read and cancelled.

Whoever may send from an account sees and cancels the jobs they queued
there. Whoever may audit its sends (``list_sends``) sees every job of
it, and whoever may change the account (``update_account``, in
``accounts.manage``) sees and cancels every job of it: so an agent that
queues too much can be stopped. A job another caller may not see is not found.
"""

from __future__ import annotations

from collections.abc import Callable
from datetime import datetime

from ....common.clock import utc_now
from ....data.models import OutboxJob, OutboxState, Page
from ....data.storage import OutboxRepository
from ....errors import ConflictError, ForbiddenError, missing
from ... import changes, paging
from ...rights import Access
from ..calls import Calls
from .sending import SendControl

CURSOR = "o_"
CANCELLED = "cancelled_by_user"


class OutboxJobs:
    def __init__(
        self,
        calls: Calls,
        sends: SendControl,
        jobs: OutboxRepository,
        clock: Callable[[], datetime] = utc_now,
    ) -> None:
        self._calls = calls
        self._sends = sends
        self._jobs = jobs
        self._clock = clock

    def list_outbox(
        self,
        access: Access,
        account_id: str,
        *,
        limit: int,
        cursor: str | None,
        state: OutboxState | None = None,
    ) -> Page[OutboxJob]:
        """The jobs of the account the caller may see, newest first."""
        whose = self._whose(access, account_id)
        found = self._jobs.list(
            account_id,
            limit=limit + 1,
            before=paging.decode_before(CURSOR, cursor),
            user_id=whose,
            state=state,
        )
        items, more = paging.split_page(found, limit)
        next_cursor = None
        if more:
            last = items[-1]
            next_cursor = paging.encode_before(CURSOR, last.created_at, last.id)
        return Page[OutboxJob](items=items, next_cursor=next_cursor)

    def get_outbox_job(self, access: Access, account_id: str, job_id: str) -> OutboxJob:
        """One job, if the caller may see it."""
        whose = self._whose(access, account_id)
        job = self._find(account_id, job_id)
        if whose is not None and job.user_id != whose:
            raise missing("outbox job", job_id)
        return job

    def cancel_send(self, access: Access, account_id: str, job_id: str) -> OutboxJob:
        """Cancel a job that waits. Its draft stays. A job already being
        sent, or ended, is a conflict."""
        job = self.get_outbox_job(access, account_id, job_id)
        own = job.user_id == access.user_id and access.allows("cancel_send", account_id)
        if not (own or access.allows("update_account", account_id)):
            raise ForbiddenError("only who queued it or manages the account cancels it")
        if job.state != "queued":
            raise ConflictError(f"the send is {job.state}, not waiting")
        ended = job.model_copy(
            update={
                "state": "cancelled",
                "last_error": CANCELLED,
                "finished_at": self._clock(),
            }
        )
        if not self._jobs.update(ended, was="queued"):
            raise ConflictError("the send is being sent now")
        self._sends.note(ended, "cancelled", CANCELLED)
        self._calls.changed(changes.SendCancelled(account_id, job.id))
        return ended

    def _whose(self, access: Access, account_id: str) -> str | None:
        """Whose jobs the caller sees: None for every one, else its own."""
        if access.allows("list_sends", account_id) or access.allows(
            "update_account", account_id
        ):
            return None
        access.require("list_outbox", account_id)
        return access.user_id

    def _find(self, account_id: str, job_id: str) -> OutboxJob:
        job = self._jobs.get(job_id)
        if job.account_id != account_id:
            raise missing("outbox job", job_id)
        return job
