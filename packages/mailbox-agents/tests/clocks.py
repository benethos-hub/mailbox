"""A clock that moves only when a test moves it: ``Clock`` for the time
of day the worker and the agents read."""

from __future__ import annotations

from datetime import UTC, datetime, timedelta

START = datetime(2026, 11, 17, 9, 0, tzinfo=UTC)


class Clock:
    """A clock a test moves by hand."""

    def __init__(self, start: datetime = START) -> None:
        self.moment = start

    def __call__(self) -> datetime:
        return self.moment

    def advance(self, **delta: float) -> None:
        self.moment += timedelta(**delta)
