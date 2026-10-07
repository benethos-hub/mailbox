"""The audit of sends (CONCEPT 7.7). It only stores. The domain decides
what a record says and what counts against a send limit."""

from __future__ import annotations

import builtins
from datetime import datetime
from typing import Protocol

from ..models import Before, SendFilter, SendOutcome, SendRecord
from .table import Table


class SendLogRepository(Protocol):
    def add(self, record: SendRecord) -> None: ...

    def sent_since(
        self, user_id: str, account_id: str, since: datetime, *, outcome: SendOutcome
    ) -> list[datetime]:
        """When the user's sends from the account with ``outcome`` happened
        after ``since``, oldest first."""
        ...

    def list(
        self,
        account_id: str,
        *,
        limit: int,
        before: Before | None,
        matching: SendFilter | None = None,
    ) -> list[SendRecord]:
        """Newest first, those older than ``before`` if given,
        and only those ``matching``."""
        ...

    def account_ids(self) -> builtins.list[str]:
        """Every account the audit has a send of, whether it exists or not."""
        ...

    def purge(self, before: datetime) -> int:
        """Remove the records older than ``before``. How many."""
        ...


class InMemorySendLogRepository:
    def __init__(self) -> None:
        self._records: Table[SendRecord] = Table("send")

    def add(self, record: SendRecord) -> None:
        self._records.add(record.id, record)

    def sent_since(
        self, user_id: str, account_id: str, since: datetime, *, outcome: SendOutcome
    ) -> list[datetime]:
        return sorted(
            r.created_at
            for r in self._records.list()
            if r.user_id == user_id
            and r.account_id == account_id
            and r.outcome == outcome
            and r.created_at > since
        )

    def list(
        self,
        account_id: str,
        *,
        limit: int,
        before: Before | None,
        matching: SendFilter | None = None,
    ) -> list[SendRecord]:
        found = sorted(
            (
                r
                for r in self._records.list()
                if r.account_id == account_id
                and (matching is None or matching.matches(r))
            ),
            key=lambda r: (r.created_at, r.id),
            reverse=True,
        )
        if before is not None:
            found = [r for r in found if Before(r.created_at, r.id) < before]
        return found[:limit]

    def account_ids(self) -> builtins.list[str]:
        return sorted({r.account_id for r in self._records.list()})

    def purge(self, before: datetime) -> int:
        gone = [r.id for r in self._records.list() if r.created_at < before]
        for record_id in gone:
            self._records.delete(record_id)
        return len(gone)
