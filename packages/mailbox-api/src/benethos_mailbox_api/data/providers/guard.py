"""Care towards one account's server (CONCEPT 5.9), whatever the protocol.

Every request passes the account's rate limiter, a rejected login is not
tried again until the credential changes, and an unreachable server is
retried with backoff and then left alone for a growing pause.
"""

from __future__ import annotations

import math
import time
from collections.abc import Callable, Iterator
from contextlib import contextmanager
from functools import partial
from typing import TypeVar

from ...errors import ProviderAuthError, ProviderError, ProviderUnavailableError
from .ratelimit import Clock, Sleep, TokenBucket, backoff

T = TypeVar("T")

ATTEMPTS = 3
FIRST_PAUSE = 30.0
LONGEST_PAUSE = 900.0


class Guard:
    """The state of one account towards its server, shared by all the
    adapter's connections to it."""

    def __init__(
        self,
        per_minute: float,
        clock: Clock = time.monotonic,
        sleep: Sleep = time.sleep,
        jitter: Callable[[float, float], float] | None = None,
    ) -> None:
        self._bucket = TokenBucket(per_minute, burst=10, clock=clock, sleep=sleep)
        self._clock = clock
        self._sleep = sleep
        self._backoff = partial(backoff, jitter=jitter) if jitter else backoff
        self._login_rejected = False
        self._failures = 0
        self._paused_until = 0.0

    def check(self) -> None:
        """Refuse at once while a login stands rejected or the server rests."""
        if self._login_rejected:
            raise ProviderAuthError(
                "the server rejected the login before: no new attempt until the "
                "credential is replaced or the account is verified"
            )
        wait = self._paused_until - self._clock()
        if wait > 0:
            raise ProviderUnavailableError(
                f"the mail server was unreachable: next attempt in {math.ceil(wait)}s"
            )

    def acquire(self) -> None:
        """One request's share of the rate, waiting for it if need be."""
        self._bucket.acquire()

    @contextmanager
    def refused_logins(self) -> Iterator[None]:
        """A login the server rejects inside blocks further attempts."""
        try:
            yield
        except ProviderAuthError:
            self._login_rejected = True
            raise

    def reset(self) -> None:
        """Forget rejections and pauses, before a deliberate new attempt."""
        self._login_rejected = False
        self._failures = 0
        self._paused_until = 0.0

    def once(self, step: Callable[[], T]) -> T:
        """Run ``step`` once, paced, refused while a login stands rejected
        or the server rests, and a rejected login inside blocks further
        attempts. For a connection made and dropped within the step, such
        as a send over SMTP."""
        self.check()
        self.acquire()
        with self.refused_logins():
            return step()

    def attempts(self, step: Callable[[], T], drop: Callable[[], None]) -> T:
        """Run ``step`` with retries while the server is unreachable. After
        any failure ``drop`` discards the connection. After the last attempt
        the server gets a pause."""
        self.check()
        last: ProviderUnavailableError | None = None
        for attempt in range(ATTEMPTS):
            if attempt:
                self._sleep(self._backoff(attempt - 1))
            try:
                with self.refused_logins():
                    self.acquire()
                    result = step()
            except ProviderUnavailableError as exc:
                drop()
                last = exc
                continue
            except (ProviderAuthError, ProviderError):
                # Not a connection problem, so retrying will not help. The
                # connection may still be in a bad state: start afresh.
                drop()
                raise
            self._failures = 0
            return result
        self._pause()
        assert last is not None
        raise last

    def _pause(self) -> None:
        self._failures += 1
        pause = min(LONGEST_PAUSE, FIRST_PAUSE * 2 ** (self._failures - 1))
        self._paused_until = self._clock() + pause
