"""The audit of administration (docs/AUDIT.md): the activities marked
``audited``, kept in the database for the days the settings say.

The log is for the operator and may be dropped. The audit answers who
changed what, when, for as long as the deployment keeps it. A record is
the activity's line in fields: who, how they came, from where, what
they touched, and the outcome. ``audit`` in ``service`` reads it.
"""

from __future__ import annotations

from collections.abc import Callable
from dataclasses import dataclass
from datetime import datetime, timedelta
from typing import Any

from ...common.clock import iso, parse_iso, utc_now
from ...common.ids import new_id
from ...common.redact import redact
from ...data.models import ActivityFilter, ActivityRecord, Page
from ...data.storage import AuditRepository
from .. import paging
from ..rights import Access
from .base import Activity

# Days a record is kept, unless the settings say otherwise. 0 keeps
# every record.
KEEP_DAYS = 90
# How often at most old records are purged while activities come in.
PURGE_EVERY = timedelta(hours=1)
CURSOR = "a_"


@dataclass(frozen=True)
class Purged:
    """What a purge removed: how many records, older than when."""

    count: int
    before: datetime


class Audit:
    def __init__(
        self,
        store: AuditRepository,
        clock: Callable[[], datetime] = utc_now,
        days: int = KEEP_DAYS,
    ) -> None:
        """``days`` is how long a record is kept, 0 for ever."""
        self._store = store
        self._clock = clock
        self._days = days
        self._purged_at: datetime | None = None

    @property
    def days(self) -> int:
        """How long a record is kept, 0 for ever."""
        return self._days

    def keep(self, activity: Activity) -> Purged | None:
        """Store the activity. Old records go first when a purge is due:
        what it removed, if anything."""
        purged = self._purge_when_due()
        by = activity.by
        self._store.add(
            ActivityRecord(
                id=new_id("evt"),
                at=activity.at or self._clock(),
                activity=activity.kind(),
                user_id=by.user_id,
                user_name=by.name,
                credential=by.credential,
                record=activity.touched(),
                source=by.source,
                outcome=activity.outcome,
                # No line names a secret on purpose. One a library put
                # into an error is masked here as in the log.
                detail=redact(activity.detail()),
            )
        )
        return purged

    def purge(self) -> Purged | None:
        """Remove the records older than the days to keep."""
        if not self._days:
            return None
        now = self._clock()
        before = now - timedelta(days=self._days)
        count = self._store.purge(before)
        self._purged_at = now
        return Purged(count, before) if count else None

    def _purge_when_due(self) -> Purged | None:
        if self._purged_at is None or self._clock() - self._purged_at >= PURGE_EVERY:
            return self.purge()
        return None

    def list_activity(
        self,
        access: Access,
        *,
        limit: int,
        cursor: str | None = None,
        matching: ActivityFilter | None = None,
    ) -> Page[ActivityRecord]:
        """The audit, newest first."""
        access.require("list_activity")
        before = None
        if cursor is not None:
            before = paging.decode_cursor(CURSOR, cursor, _before)
        found = self._store.list(limit=limit + 1, before=before, matching=matching)
        records, more = paging.split_page(found, limit)
        next_cursor = None
        if more:
            last = records[-1]
            next_cursor = paging.encode_cursor(CURSOR, [iso(last.at), last.id])
        return Page[ActivityRecord](items=records, next_cursor=next_cursor)


def _before(carried: Any) -> tuple[datetime, str]:
    """The time and the id a cursor of the audit continues before."""
    at, record_id = carried
    return parse_iso(str(at)), str(record_id)
