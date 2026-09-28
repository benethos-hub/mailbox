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

from collections.abc import Callable, Collection, Iterable
from datetime import datetime, timedelta
from typing import Any

from ...common.clock import utc_now
from ...data.models import FEED_KINDS, Change, ChangePage, ChangeRecord
from ...data.storage import ChangeLogRepository, LoggedChange
from ...errors import ChangesExpiredError
from .. import paging
from ..activity import SERVICE, ActivityLog
from ..activity import changes as said
from .catalogue import MailboxChange

STATE = "chs_"
DEFAULT_DAYS = 7
# How often at most the log is purged while changes come in.
PURGE_EVERY = timedelta(hours=1)


class ChangeFeed:
    def __init__(
        self,
        log: ChangeLogRepository,
        *,
        days: int = DEFAULT_DAYS,
        clock: Callable[[], datetime] = utc_now,
        activity: ActivityLog | None = None,
    ) -> None:
        self._log = log
        self._keep = timedelta(days=days)
        self._clock = clock
        self._activity = activity or ActivityLog(clock)
        self._purged_at: datetime | None = None

    def record(self, change: MailboxChange) -> None:
        """One record for each id the change names, in this order."""
        now = self._clock()
        records = [
            ChangeRecord(type=change.kind, id=i, account_id=change.account_id, at=now)
            for i in dict.fromkeys(change.ids())
        ]
        if not records:
            return
        self._log.append(records)
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
        found, more = paging.split_page(
            self._log.after(account_ids, seq, limit=limit + 1, types=FEED_KINDS), limit
        )
        end = found[-1].seq if more else max([last, *(e.seq for e in found)])
        return ChangePage(
            changes=[Change.model_validate(e.record.model_dump()) for e in found],
            state=_state(end),
            more=more,
        )

    def after(
        self,
        account_ids: Iterable[str],
        seq: int,
        *,
        limit: int,
        types: Collection[str] | None = None,
    ) -> list[LoggedChange]:
        """The records of these accounts after point ``seq``, oldest first."""
        return self._log.after(account_ids, seq, limit=limit, types=types)

    def horizon(self) -> int:
        """Records up to this point were purged."""
        return self._log.horizon()

    def last(self) -> int:
        """The current point in the feed."""
        return self._log.last()

    def purge(self) -> None:
        """Removes the changes older than the days to keep."""
        now = self._clock()
        before = now - self._keep
        purged = self._log.purge(before)
        self._purged_at = now
        if purged:
            self._activity.record(
                said.ChangesPurged(by=SERVICE, count=purged, before=before)
            )

    def forget_account(self, account_id: str) -> None:
        self._log.forget_account(account_id)


def _state(seq: int) -> str:
    return paging.encode_cursor(STATE, seq)


def _seq(state: str) -> int:
    return paging.decode_cursor(
        STATE, state, _point, refusal="since is not a state of the change feed"
    )


def _point(carried: Any) -> int:
    if not isinstance(carried, int) or isinstance(carried, bool) or carried < 0:
        raise ValueError("not a point in the feed")
    return carried
