"""Slowing down guessed credentials (CONCEPT 7.5).

A source, normally the client address, that fails to sign in ``limit``
times within ``window`` is locked out for ``lockout``. During the lockout
every attempt from that source answers "too many attempts" without the
credential being checked, so a guesser learns nothing while locked. A
successful sign-in clears the source's failures.

The throttle knows nothing of the credential: a bearer token today, a
password with TOTP or a passkey later all count the same way. Every
sign-in path hands its source to ``AuthService``, which asks the throttle
before and tells it afterwards.

The state is in memory and per process. A restart forgets it, which is
acceptable for what it prevents: an online guess at an operator-chosen
admin key. The number of sources kept is capped, so spoofed sources cannot
grow the memory without bound.
"""

from __future__ import annotations

import math
from collections import OrderedDict, deque
from collections.abc import Callable
from datetime import datetime, timedelta

from ..common.clock import utc_now
from ..errors import RateLimitedError

LIMIT = 10
WINDOW = timedelta(minutes=15)
LOCKOUT = timedelta(minutes=15)
# How many sources are remembered at most. The oldest is forgotten first.
MAX_SOURCES = 10_000


class SignInThrottle:
    def __init__(
        self,
        limit: int = LIMIT,
        window: timedelta = WINDOW,
        lockout: timedelta = LOCKOUT,
        max_sources: int = MAX_SOURCES,
        clock: Callable[[], datetime] = utc_now,
    ) -> None:
        if limit < 1 or max_sources < 1:
            raise ValueError("the limit and the number of sources must be positive")
        self._limit = limit
        self._window = window
        self._lockout = lockout
        self._max_sources = max_sources
        self._clock = clock
        # Per source: when it failed, oldest first, and until when it is
        # locked. Ordered by last use, so the least recent is dropped first.
        self._failures: OrderedDict[str, deque[datetime]] = OrderedDict()
        self._locked: dict[str, datetime] = {}

    def check(self, source: str) -> None:
        """Raises ``RateLimitedError`` while ``source`` is locked out."""
        until = self._locked.get(source)
        if until is None:
            return
        now = self._clock()
        if until <= now:
            del self._locked[source]
            self._failures.pop(source, None)
            return
        seconds = math.ceil((until - now).total_seconds())
        raise RateLimitedError(
            f"too many failed sign-in attempts, try again in {seconds} seconds",
            retry_after=seconds,
        )

    def failed(self, source: str) -> None:
        """One more failed attempt. The ``limit``-th within ``window`` locks
        the source out."""
        now = self._clock()
        failures = self._failures.pop(source, None) or deque()
        while failures and now - failures[0] > self._window:
            failures.popleft()
        failures.append(now)
        self._failures[source] = failures
        while len(self._failures) > self._max_sources:
            oldest, _ = self._failures.popitem(last=False)
            self._locked.pop(oldest, None)
        if len(failures) >= self._limit:
            self._locked[source] = now + self._lockout
            failures.clear()

    def succeeded(self, source: str) -> None:
        """A successful sign-in clears the source."""
        self._failures.pop(source, None)
        self._locked.pop(source, None)
