"""How long records are kept, and when the old ones are due to go.

A service that keeps records calls ``due`` as new ones come in. The
first call is due at once, so a service that has just started purges
before it writes. Then at most once per ``every``. The service removes
what is older than ``cutoff`` and says ``done``.
"""

from __future__ import annotations

from datetime import datetime, timedelta

# How often at most old records are purged while new ones come in.
PURGE_EVERY = timedelta(hours=1)


class Retention:
    def __init__(self, days: int, every: timedelta = PURGE_EVERY) -> None:
        """``days`` is how long a record is kept, 0 for ever."""
        self._days = days
        self._every = every
        self._done_at: datetime | None = None

    @property
    def days(self) -> int:
        """How long a record is kept, 0 for ever."""
        return self._days

    def due(self, now: datetime) -> bool:
        """Whether old records are to go now. Never when kept for ever."""
        if not self._days:
            return False
        return self._done_at is None or now - self._done_at >= self._every

    def cutoff(self, now: datetime) -> datetime:
        """Records older than this go."""
        return now - timedelta(days=self._days)

    def done(self, now: datetime) -> None:
        """The old records went at ``now``."""
        self._done_at = now
