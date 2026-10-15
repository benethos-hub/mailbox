"""Clocks that move only when a test moves them: ``Clock`` for the time of
day the services keep, ``Seconds`` for a monotonic clock and its sleep."""

from __future__ import annotations

from datetime import UTC, datetime, timedelta

NOW = datetime(2026, 9, 26, 12, 0, tzinfo=UTC)


class Clock:
    """The time of day, in UTC, as a service's ``clock`` reads it."""

    def __init__(self, now: datetime = NOW) -> None:
        self.now = now

    def __call__(self) -> datetime:
        return self.now

    def tick(self, **delta: float) -> None:
        """On by a ``timedelta`` of ``delta``: ``tick(minutes=5)``."""
        self.now += timedelta(**delta)


class Seconds:
    """A monotonic clock in seconds, and a sleep that moves it on."""

    def __init__(self, now: float = 1000.0) -> None:
        self.now = now
        self.sleeps: list[float] = []

    def __call__(self) -> float:
        return self.now

    def sleep(self, seconds: float) -> None:
        self.sleeps.append(seconds)
        self.now += seconds
