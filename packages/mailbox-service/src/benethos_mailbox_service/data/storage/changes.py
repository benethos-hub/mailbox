"""The change log behind the change feed (CONCEPT 6.5).

Every change gets the next number of one sequence across all accounts, so
a single number marks a point in the feed. The repository only stores. The
domain decides what counts as a change and how long it is kept.
"""

from __future__ import annotations

from collections.abc import Collection, Iterable
from dataclasses import dataclass
from datetime import datetime
from typing import Protocol

from ..models import ChangeRecord


@dataclass(frozen=True, slots=True)
class LoggedChange:
    seq: int
    record: ChangeRecord


class ChangeLogRepository(Protocol):
    def append(self, records: Iterable[ChangeRecord]) -> None:
        """Appends in order, each with the next sequence number."""
        ...

    def after(
        self,
        account_ids: Iterable[str],
        seq: int,
        *,
        limit: int,
        types: Collection[str] | None = None,
    ) -> list[LoggedChange]:
        """Oldest first, those of these accounts numbered above ``seq``, of
        ``types`` only if given."""
        ...

    def last(self) -> int:
        """The highest number handed out, 0 before the first change. It
        never goes back, not even when changes are purged."""
        ...

    def horizon(self) -> int:
        """The highest number ``purge`` removed, 0 if it removed none. A
        point in the feed below it has lost changes."""
        ...

    def purge(self, before: datetime) -> int:
        """Removes the changes older than ``before``. Returns how many."""
        ...

    def forget_account(self, account_id: str) -> None: ...


class InMemoryChangeLogRepository:
    def __init__(self) -> None:
        self._log: list[LoggedChange] = []
        self._last = 0
        self._horizon = 0

    def append(self, records: Iterable[ChangeRecord]) -> None:
        for record in records:
            self._last += 1
            self._log.append(LoggedChange(self._last, record))

    def after(
        self,
        account_ids: Iterable[str],
        seq: int,
        *,
        limit: int,
        types: Collection[str] | None = None,
    ) -> list[LoggedChange]:
        wanted = set(account_ids)
        found = [
            e
            for e in self._log
            if e.seq > seq
            and e.record.account_id in wanted
            and (types is None or e.record.type in types)
        ]
        return found[:limit]

    def last(self) -> int:
        return self._last

    def horizon(self) -> int:
        return self._horizon

    def purge(self, before: datetime) -> int:
        old = [e for e in self._log if e.record.at < before]
        if old:
            self._horizon = max(self._horizon, max(e.seq for e in old))
            self._log = [e for e in self._log if e.record.at >= before]
        return len(old)

    def forget_account(self, account_id: str) -> None:
        self._log = [e for e in self._log if e.record.account_id != account_id]
