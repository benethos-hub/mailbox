"""The recorder: each activity as one line of the log, and the record
of the audit for one marked ``audited``.

The line goes to the logger of the activity, ``activity.<area>.<name>``
below the service's package, so the level of the service's log applies,
and a level set on one name applies to it alone. The audit of
docs/AUDIT.md keeps its record whatever the level: nothing else writes
one.
"""

from __future__ import annotations

import logging
import re
from collections.abc import Callable, Iterator
from contextlib import AbstractContextManager, contextmanager, nullcontext
from contextvars import ContextVar
from dataclasses import replace
from datetime import datetime
from typing import TypeVar

from ...common.clock import utc_now
from ...errors import MailboxServiceError
from .audit import Audit
from .base import SERVICE, Activity, Failure
from .catalogue import system

PACKAGE = __name__.partition(".")[0]

A = TypeVar("A", bound=Activity)


def logger_of(activity: type[Activity]) -> logging.Logger:
    return logging.getLogger(f"{PACKAGE}.{activity.source()}")


# What ends a line to a reader of the log: CR and LF, the other control
# characters, and the line breaks beyond ASCII that ``str.splitlines``
# breaks on. A name a caller chose must not start a line of its own.
_BREAKS = re.compile(r"[\x00-\x08\x0a-\x1f\x7f\x85\u2028\u2029]")


def one_line(text: str) -> str:
    """``text`` as one line: each break written as its escape, such as a
    line feed as backslash and n."""
    return _BREAKS.sub(lambda m: m.group().encode("unicode_escape").decode(), text)


class ActivityLog:
    def __init__(
        self,
        clock: Callable[[], datetime] = utc_now,
        audit: Audit | None = None,
        transaction: Callable[[], AbstractContextManager[object]] | None = None,
    ) -> None:
        """``audit``: where an activity marked ``audited`` is kept. None
        keeps nothing, for a service or a test that needs no audit.
        ``transaction``: one transaction of the store that holds the
        audit and the records it is about, for ``atomic``."""
        self._clock = clock
        self._audit = audit
        self._transaction = transaction or nullcontext
        # The lines of the activities recorded in ``atomic``, written once
        # its transaction is committed. Per context, so neither another
        # thread nor another task writes into them.
        self._waiting: ContextVar[list[Activity] | None] = ContextVar(
            "waiting", default=None
        )

    @contextmanager
    def atomic(self) -> Iterator[None]:
        """The changes to the store in the block and the audit records of
        the activities recorded in it, in one transaction (docs/AUDIT.md
        4). A record that cannot be kept undoes the changes and raises.
        The lines of the log follow once the transaction is committed,
        none when it is not. Inside another block, a part of it.

        The block must not await: the transaction holds the store, and
        another task would write into it."""
        waiting = self._waiting.get()
        outer = waiting is None
        if waiting is None:
            waiting = []
            token = self._waiting.set(waiting)
        start = len(waiting)
        try:
            with self._transaction():
                yield
        except BaseException:
            del waiting[start:]
            raise
        finally:
            if outer:
                self._waiting.reset(token)
        if outer:
            for activity in waiting:
                self._write(activity)

    def record(self, activity: A) -> A:
        """Write the activity's line at its level, and keep it in the
        audit when it is marked so. A failure that is not one of ours is
        an error, with its traceback. Returns the activity with its time,
        for tests. Inside ``atomic`` the record is kept in its
        transaction, and the line waits for it."""
        if activity.at is None:
            activity = replace(activity, at=self._clock())
        waiting = self._waiting.get()
        if waiting is None:
            self._write(activity)
            if activity.audited and self._audit is not None:
                self._keep(self._audit, activity)
            return activity
        if activity.audited and self._audit is not None:
            # Raised: the change goes back with the transaction.
            purged = self._audit.keep(activity)
            if purged is not None:
                self.record(
                    system.AuditPurged(
                        by=SERVICE, count=purged.count, before=purged.before
                    )
                )
        waiting.append(activity)
        return activity

    def _write(self, activity: Activity) -> None:
        """The activity's line, at its level."""
        level = activity.level
        exc_info = None
        if isinstance(activity, Failure) and not activity.ours:
            level = max(level, logging.ERROR)
            error = activity.error
            exc_info = (type(error), error, error.__traceback__)
        log = logger_of(type(activity))
        # The line is only built when it is written.
        if log.isEnabledFor(level):
            log.log(level, "%s", one_line(activity.line()), exc_info=exc_info)

    def _keep(self, audit: Audit, activity: Activity) -> None:
        """The audit's record of an activity outside ``atomic``, such as
        an attempt that changed nothing. What it was about has happened,
        so a failure to keep it is recorded, not raised."""
        try:
            purged = audit.keep(activity)
        except Exception as exc:
            self.record(
                system.NotAudited(by=SERVICE, activity=activity.kind(), error=exc)
            )
            return
        if purged is not None:
            self.record(
                system.AuditPurged(by=SERVICE, count=purged.count, before=purged.before)
            )

    @contextmanager
    def on_failure(
        self, make: Callable[[MailboxServiceError], Activity]
    ) -> Iterator[None]:
        """A failure of ours in the block is recorded as the activity
        ``make`` builds from it, and raised on."""
        try:
            yield
        except MailboxServiceError as exc:
            self.record(make(exc))
            raise

    @contextmanager
    def fail_quietly(self, make: Callable[[Exception], Activity]) -> Iterator[None]:
        """A step that may fail only into the log: any failure in the block
        is recorded as the activity ``make`` builds from it, and goes no
        further. For what follows a send, which a client must not take for
        a failure."""
        try:
            yield
        except Exception as exc:
            self.record(make(exc))
