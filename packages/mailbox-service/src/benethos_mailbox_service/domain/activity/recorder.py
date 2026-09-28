"""The recorder: each activity as one line of the log.

The line goes to the logger of the activity, ``activity.<area>.<name>``
below the service's package, so the level of the service's log applies,
and a level set on one name applies to it alone. The audit of
docs/AUDIT.md will be written here as well.
"""

from __future__ import annotations

import logging
from collections.abc import Callable, Iterator
from contextlib import contextmanager
from dataclasses import replace
from datetime import datetime
from typing import TypeVar

from ...common.clock import utc_now
from ...errors import MailboxServiceError
from .base import Activity, Failure

PACKAGE = __name__.partition(".")[0]

A = TypeVar("A", bound=Activity)


def logger_of(activity: type[Activity]) -> logging.Logger:
    return logging.getLogger(f"{PACKAGE}.{activity.source()}")


class ActivityLog:
    def __init__(self, clock: Callable[[], datetime] = utc_now) -> None:
        self._clock = clock

    def record(self, activity: A) -> A:
        """Write the activity's line at its level. A failure that is not one
        of ours is an error, with its traceback. Returns the activity with
        its time, for tests."""
        if activity.at is None:
            activity = replace(activity, at=self._clock())
        level = activity.level
        exc_info = None
        if isinstance(activity, Failure) and not activity.ours:
            level = max(level, logging.ERROR)
            error = activity.error
            exc_info = (type(error), error, error.__traceback__)
        log = logger_of(type(activity))
        # The line is only built when it is written.
        if log.isEnabledFor(level):
            log.log(level, "%s", activity.line(), exc_info=exc_info)
        return activity

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
