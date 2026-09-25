"""The change feed: records which message was created, updated or deleted
(CONCEPT 6.5).

The sync pass records what it finds at the provider. Changes made through
the API are recorded where they are made, for every provider. Old changes
are purged as new ones come in, so the log stays small without the worker.

A point in the feed is handed out as an opaque state. It is one number of a
sequence across all accounts, so the state of one account's feed and of the
feed across accounts mean the same point.
"""

from __future__ import annotations

from collections.abc import Callable, Iterable
from datetime import datetime, timedelta

from ..common import opaque
from ..common.clock import utc_now
from ..data.models import Change, ChangePage, ChangeType
from ..data.storage import (
    ChangeLogRepository,
    InMemoryChangeLogRepository,
    LoggedChange,
)
from ..errors import BadRequestError, ChangesExpiredError

STATE = "chs_"
DEFAULT_DAYS = 7
# How often at most the log is purged while changes come in.
PURGE_EVERY = timedelta(hours=1)


class ChangeFeed:
    def __init__(
        self,
        log: ChangeLogRepository | None = None,
        *,
        days: int = DEFAULT_DAYS,
        clock: Callable[[], datetime] = utc_now,
    ) -> None:
        self._log = log if log is not None else InMemoryChangeLogRepository()
        self._keep = timedelta(days=days)
        self._clock = clock
        self._purged_at: datetime | None = None

    def record(
        self, account_id: str, type: ChangeType, message_ids: Iterable[str]
    ) -> None:
        """One change of ``type`` for each message, in this order."""
        now = self._clock()
        changes = [
            Change(type=type, id=message_id, account_id=account_id, at=now)
            for message_id in dict.fromkeys(message_ids)
        ]
        if not changes:
            return
        self._log.append(changes)
        if self._purged_at is None or now - self._purged_at >= PURGE_EVERY:
            self.purge()

    def page(
        self, account_ids: list[str], since: str | None, *, limit: int
    ) -> ChangePage:
        """The changes of these accounts after the point ``since``, at most
        ``limit``. Without ``since`` only the current point."""
        # Read first: a change recorded meanwhile is in the answer or after
        # the state it hands out, never skipped.
        last = self._log.last()
        if since is None:
            return ChangePage(changes=[], state=_state(last), more=False)
        seq = _seq(since)
        if seq > last or seq < self._log.horizon():
            raise ChangesExpiredError(
                "this state is unknown or older than the changes kept: start"
                " again without since"
            )
        found = self._log.after(account_ids, seq, limit=limit + 1)
        more = len(found) > limit
        found = found[:limit]
        end = found[-1].seq if more else max([last, *(e.seq for e in found)])
        return ChangePage(
            changes=[e.change for e in found], state=_state(end), more=more
        )

    def after(
        self, account_ids: Iterable[str], seq: int, *, limit: int
    ) -> list[LoggedChange]:
        """The changes of these accounts after point ``seq``, oldest first."""
        return self._log.after(account_ids, seq, limit=limit)

    def last(self) -> int:
        """The current point in the feed."""
        return self._log.last()

    def purge(self) -> None:
        """Removes the changes older than the days to keep."""
        now = self._clock()
        self._log.purge(now - self._keep)
        self._purged_at = now

    def forget_account(self, account_id: str) -> None:
        self._log.forget_account(account_id)


def _state(seq: int) -> str:
    return opaque.encode(STATE, seq)


def _seq(state: str) -> int:
    try:
        seq = opaque.decode(STATE, state)
    except ValueError:
        raise BadRequestError("since is not a state of the change feed") from None
    if not isinstance(seq, int) or isinstance(seq, bool) or seq < 0:
        raise BadRequestError("since is not a state of the change feed")
    return seq
