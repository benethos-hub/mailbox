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
from datetime import datetime

from benethos_mailbox_common.redact import redact

from ...common.clock import utc_now
from ...common.retention import Retention
from ...common.secret import new_id
from ...data.models import ActivityFilter, ActivityRecord, Page
from ...data.storage import AuditRepository
from .. import paging
from ..rights import Access
from .base import Activity

# Days a record is kept, unless the settings say otherwise. 0 keeps
# every record.
KEEP_DAYS = 90
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
        self._retention = Retention(days)

    @property
    def days(self) -> int:
        """How long a record is kept, 0 for ever."""
        return self._retention.days

    def keep(self, activity: Activity) -> Purged | None:
        """Store the activity. Old records go first when a purge is due:
        what it removed, if anything."""
        purged = self.purge() if self._retention.due(self._clock()) else None
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
        if not self._retention.days:
            return None
        now = self._clock()
        before = self._retention.cutoff(now)
        count = self._store.purge(before)
        self._retention.done(now)
        return Purged(count, before) if count else None

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
        before = paging.decode_before(CURSOR, cursor)
        found = self._store.list(limit=limit + 1, before=before, matching=matching)
        records, more = paging.split_page(found, limit)
        next_cursor = None
        if more:
            last = records[-1]
            next_cursor = paging.encode_before(CURSOR, last.at, last.id)
        return Page[ActivityRecord](items=records, next_cursor=next_cursor)


def audited() -> list[str]:
    """The names of every activity the audit keeps, sorted."""
    found: set[str] = set()
    todo: list[type[Activity]] = [Activity]
    while todo:
        for cls in todo.pop().__subclasses__():
            todo.append(cls)
            if cls.audited and cls.name:
                found.add(cls.kind())
    return sorted(found)
