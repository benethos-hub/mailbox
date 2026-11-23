"""The audit of administration (docs/mailbox-service/AUDIT.md). It only stores. The
domain decides which activities it keeps and what a record says."""

from __future__ import annotations

from datetime import datetime
from typing import Protocol

from ..models import ActivityFilter, ActivityRecord, Before
from .table import Table


class AuditRepository(Protocol):
    def add(self, record: ActivityRecord) -> None: ...

    def list(
        self,
        *,
        limit: int,
        before: Before | None,
        matching: ActivityFilter | None = None,
    ) -> list[ActivityRecord]:
        """Newest first, those older than ``before`` if given,
        and only those ``matching``."""
        ...

    def purge(self, before: datetime) -> int:
        """Remove the records older than ``before``. How many."""
        ...


class InMemoryAuditRepository:
    def __init__(self) -> None:
        self._records: Table[ActivityRecord] = Table("activity")

    def add(self, record: ActivityRecord) -> None:
        self._records.add(record.id, record)

    def list(
        self,
        *,
        limit: int,
        before: Before | None,
        matching: ActivityFilter | None = None,
    ) -> list[ActivityRecord]:
        found = sorted(
            (
                r
                for r in self._records.list()
                if (matching is None or matching.matches(r))
                and (before is None or Before(r.at, r.id) < before)
            ),
            key=lambda r: (r.at, r.id),
            reverse=True,
        )
        return found[:limit]

    def purge(self, before: datetime) -> int:
        return self._records.drop_where(lambda r: r.at < before)
