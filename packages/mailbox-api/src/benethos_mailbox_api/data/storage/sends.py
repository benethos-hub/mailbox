"""The audit of sends (CONCEPT 7.7). Stores; the domain decides what a
record says and what counts against a send limit."""

from __future__ import annotations

from datetime import datetime
from typing import Protocol

from ..models import SendRecord


class SendLogRepository(Protocol):
    def add(self, record: SendRecord) -> None: ...

    def sent_since(
        self, user_id: str, account_id: str, since: datetime
    ) -> list[datetime]:
        """When the user sent from the account after ``since``, oldest first;
        only sends with the outcome ``sent``."""
        ...

    def list(
        self, account_id: str, *, limit: int, before: tuple[datetime, str] | None
    ) -> list[SendRecord]:
        """Newest first, those older than ``before`` (time, id) if given."""
        ...


class InMemorySendLogRepository:
    def __init__(self) -> None:
        self._records: list[SendRecord] = []

    def add(self, record: SendRecord) -> None:
        self._records.append(record)

    def sent_since(
        self, user_id: str, account_id: str, since: datetime
    ) -> list[datetime]:
        return sorted(
            r.created_at
            for r in self._records
            if r.user_id == user_id
            and r.account_id == account_id
            and r.outcome == "sent"
            and r.created_at > since
        )

    def list(
        self, account_id: str, *, limit: int, before: tuple[datetime, str] | None
    ) -> list[SendRecord]:
        found = sorted(
            (r for r in self._records if r.account_id == account_id),
            key=lambda r: (r.created_at, r.id),
            reverse=True,
        )
        if before is not None:
            found = [r for r in found if (r.created_at, r.id) < before]
        return found[:limit]
