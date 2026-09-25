"""The change log behind the change feed (CONCEPT 6.5).

Every change gets the next number of one sequence across all accounts, so
a single number marks a point in the feed. The repository only stores. The
domain decides what counts as a change and how long it is kept.
"""

from __future__ import annotations

from collections.abc import Iterable
from dataclasses import dataclass
from datetime import datetime
from typing import Protocol

from ..models.changes import Change


@dataclass(frozen=True)
class LoggedChange:
    seq: int
    change: Change


class ChangeLogRepository(Protocol):
    def append(self, changes: Iterable[Change]) -> None:
        """Appends in order, each with the next sequence number."""
        ...

    def after(
        self, account_ids: Iterable[str], seq: int, *, limit: int
    ) -> list[LoggedChange]:
        """Oldest first, those of these accounts numbered above ``seq``."""
        ...

    def last(self) -> int:
        """The highest number handed out, 0 before the first change. It
        never goes back, not even when changes are purged."""
        ...

    def horizon(self) -> int:
        """The highest number ``purge`` removed, 0 if it removed none. A
        point in the feed below it has lost changes."""
        ...

    def purge(self, before: datetime) -> None:
        """Removes the changes older than ``before``."""
        ...

    def forget_account(self, account_id: str) -> None: ...


class InMemoryChangeLogRepository:
    def __init__(self) -> None:
        self._log: list[LoggedChange] = []
        self._last = 0
        self._horizon = 0

    def append(self, changes: Iterable[Change]) -> None:
        for change in changes:
            self._last += 1
            self._log.append(LoggedChange(self._last, change))

    def after(
        self, account_ids: Iterable[str], seq: int, *, limit: int
    ) -> list[LoggedChange]:
        wanted = set(account_ids)
        found = [e for e in self._log if e.seq > seq and e.change.account_id in wanted]
        return found[:limit]

    def last(self) -> int:
        return self._last

    def horizon(self) -> int:
        return self._horizon

    def purge(self, before: datetime) -> None:
        old = [e for e in self._log if e.change.at < before]
        if old:
            self._horizon = max(self._horizon, max(e.seq for e in old))
            self._log = [e for e in self._log if e.change.at >= before]

    def forget_account(self, account_id: str) -> None:
        self._log = [e for e in self._log if e.change.account_id != account_id]
