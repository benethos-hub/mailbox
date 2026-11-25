"""The jobs of the outbox. It only stores. The domain decides when a job
is due and what its state becomes."""

from __future__ import annotations

import builtins
from datetime import datetime
from typing import Protocol

from ..models import Before, OutboxJob, OutboxState
from .table import Table


class OutboxRepository(Protocol):
    def add(self, job: OutboxJob) -> None: ...

    def get(self, job_id: str) -> OutboxJob:
        """The job, or ``NotFoundError``."""
        ...

    def update(self, job: OutboxJob, *, was: OutboxState) -> bool:
        """Store ``job`` if its stored state is still ``was``. Whether it
        was stored: two runs never take the same job."""
        ...

    def open(self) -> builtins.list[OutboxJob]:
        """Every job the runner still works on, the earliest due first."""
        ...

    def list(
        self,
        account_id: str,
        *,
        limit: int,
        before: Before | None,
        user_id: str | None = None,
        state: OutboxState | None = None,
    ) -> builtins.list[OutboxJob]:
        """Newest first, those older than ``before`` if given, of
        ``user_id`` and in ``state`` if given."""
        ...

    def purge(self, before: datetime) -> int:
        """Remove the finished jobs that finished before ``before``. How many."""
        ...


class InMemoryOutboxRepository:
    def __init__(self) -> None:
        self._jobs: Table[OutboxJob] = Table("outbox job")

    def add(self, job: OutboxJob) -> None:
        self._jobs.add(job.id, job)

    def get(self, job_id: str) -> OutboxJob:
        return self._jobs.get(job_id)

    def update(self, job: OutboxJob, *, was: OutboxState) -> bool:
        if job.id not in self._jobs or self._jobs.get(job.id).state != was:
            return False
        self._jobs.put(job.id, job)
        return True

    def open(self) -> builtins.list[OutboxJob]:
        return sorted(
            (job for job in self._jobs.list() if job.open),
            key=lambda job: (job.due_at, job.id),
        )

    def list(
        self,
        account_id: str,
        *,
        limit: int,
        before: Before | None,
        user_id: str | None = None,
        state: OutboxState | None = None,
    ) -> builtins.list[OutboxJob]:
        found = sorted(
            (
                job
                for job in self._jobs.list()
                if job.account_id == account_id
                and (user_id is None or job.user_id == user_id)
                and (state is None or job.state == state)
            ),
            key=lambda job: (job.created_at, job.id),
            reverse=True,
        )
        if before is not None:
            found = [job for job in found if Before(job.created_at, job.id) < before]
        return found[:limit]

    def purge(self, before: datetime) -> int:
        return self._jobs.drop_where(
            lambda job: (
                not job.open
                and job.finished_at is not None
                and job.finished_at < before
            )
        )
