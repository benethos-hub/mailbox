"""A database server that is away, as its place keeps it: since when, why,
and when the next attempt to reach it comes. While it is away every
call fails at once, without touching the network, until the pause is
over. The pause doubles after each failed attempt, from one second to
thirty."""

from __future__ import annotations

import math
from collections.abc import Callable
from dataclasses import dataclass

from ....errors import StorageUnavailableError

# The pause after the first failure, and the longest one, in seconds.
FIRST_PAUSE = 1.0
LONGEST_PAUSE = 30.0


@dataclass(frozen=True, slots=True)
class Availability:
    """A change of whether the database can be reached, as a store
    reports it: away with the kind of the failure, back after so many
    seconds, or reached again with its lock held by another service."""

    away: bool
    cause: str = ""
    seconds: float = 0.0
    lock_lost: bool = False


class Outage:
    """Whether the server is away, by the clock ``clock`` in seconds."""

    def __init__(self, clock: Callable[[], float]) -> None:
        self._clock = clock
        self._since: float | None = None
        self._pause = FIRST_PAUSE
        self._next = 0.0
        self.cause = ""

    @property
    def away(self) -> bool:
        return self._since is not None

    def due(self) -> bool:
        """Whether the pause is over and another attempt may go out."""
        return self._clock() >= self._next

    def unavailable(self) -> StorageUnavailableError:
        """The error a call meets while the server is away: the seconds
        until the next attempt, at least one."""
        wait = max(1, math.ceil(self._next - self._clock()))
        return StorageUnavailableError(wait, self.cause)

    def failed(self, cause: str) -> bool:
        """An attempt failed for ``cause``, the kind of the failure. True
        when the server went away with it, False when it was away."""
        now = self._clock()
        went = self._since is None
        if went:
            self._since = now
            self._pause = FIRST_PAUSE
        else:
            self._pause = min(self._pause * 2, LONGEST_PAUSE)
        self._next = now + self._pause
        self.cause = cause
        return went

    def mended(self) -> float | None:
        """The server answered again: the seconds it was away, None when
        it was not."""
        if self._since is None:
            return None
        away = self._clock() - self._since
        self._since = None
        self._pause = FIRST_PAUSE
        self._next = 0.0
        self.cause = ""
        return away
