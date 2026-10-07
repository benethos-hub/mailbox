"""Care towards one account's server (CONCEPT 5.9), whatever the protocol.

Every request passes the account's rate limiter, a rejected login is not
tried again until the credential changes, and an unreachable server is
retried with backoff and then left alone for a growing pause.
"""

from __future__ import annotations

import threading
import time
from collections.abc import Callable, Iterator
from contextlib import contextmanager
from dataclasses import dataclass
from functools import partial
from typing import TypeVar

from ...common.ratelimit import Clock, Sleep, TokenBucket, backoff
from ...errors import ProviderAuthError, ProviderError, ProviderUnavailableError
from . import rules

T = TypeVar("T")

ATTEMPTS = 3
FIRST_PAUSE = 30.0
LONGEST_PAUSE = 900.0


@dataclass(frozen=True)
class Pace:
    """How an adapter treats one account's server: a rate a minute, how
    many requests pass at once, how often a request is tried while the
    server does not answer, and how long the server then rests, doubled
    after each further failure up to the longest. The defaults are
    cautious, for servers nobody has told us about."""

    per_minute: float = 60.0
    burst: int = 10
    attempts: int = ATTEMPTS
    first_pause: float = FIRST_PAUSE
    longest_pause: float = LONGEST_PAUSE


class Guard:
    """The state of one account towards its server, shared by all the
    adapter's connections to it."""

    def __init__(
        self,
        per_minute: float,
        burst: int = Pace.burst,
        clock: Clock = time.monotonic,
        sleep: Sleep = time.sleep,
        jitter: Callable[[float, float], float] | None = None,
        attempts: int = ATTEMPTS,
        first_pause: float = FIRST_PAUSE,
        longest_pause: float = LONGEST_PAUSE,
        name: str = "a request",
    ) -> None:
        """``name`` says whose requests are paced, in the log."""
        self._bucket = TokenBucket(
            per_minute, burst, clock=clock, sleep=sleep, name=name
        )
        self._attempts = attempts
        self._first_pause = first_pause
        self._longest_pause = longest_pause
        self._clock = clock
        self._sleep = sleep
        self._backoff = partial(backoff, jitter=jitter) if jitter else backoff
        self._login_rejected = False
        self._failures = 0
        self._paused_until = 0.0
        # The adapter's own lock covers its session. A send over SMTP runs
        # outside it, in a thread of its own, so the state here has one.
        self._state = threading.Lock()

    def check(self) -> None:
        """Refuse at once while a login stands rejected or the server rests."""
        self._check_login()
        with self._state:
            wait = self._paused_until - self._clock()
        if wait > 0:
            raise rules.resting("the mail server was unreachable", wait)

    def acquire(self) -> None:
        """One request's share of the rate, waiting for it if need be."""
        self._bucket.acquire()

    @contextmanager
    def refused_logins(self) -> Iterator[None]:
        """A login the server rejects inside blocks further attempts."""
        try:
            yield
        except ProviderAuthError:
            with self._state:
                self._login_rejected = True
            raise

    def reset(self) -> None:
        """Forget rejections and pauses, before a deliberate new attempt."""
        with self._state:
            self._login_rejected = False
            self._failures = 0
            self._paused_until = 0.0

    def once(self, step: Callable[[], T]) -> T:
        """Run ``step`` once, paced, refused while a login stands rejected,
        and a rejected login inside blocks further attempts. For a
        connection made and dropped within the step, such as a send over
        SMTP. The pause of ``attempts`` does not hold it back: the step may
        reach another server."""
        self._check_login()
        self.acquire()
        with self.refused_logins():
            return step()

    def attempts(self, step: Callable[[], T], drop: Callable[[], None]) -> T:
        """Run ``step`` with retries while the server is unreachable. After
        any failure ``drop`` discards the connection. After the last attempt
        the server gets a pause."""
        self.check()
        last: ProviderUnavailableError | None = None
        for attempt in range(self._attempts):
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
            with self._state:
                self._failures = 0
            return result
        self._pause()
        if last is None:
            raise RuntimeError("the guard made no attempt: attempts must be 1 or more")
        raise last

    def _check_login(self) -> None:
        with self._state:
            rejected = self._login_rejected
        if rejected:
            raise ProviderAuthError(
                "the server rejected the login before: no new attempt until the "
                "credential is replaced or the account is verified"
            )

    def _pause(self) -> None:
        with self._state:
            self._failures += 1
            pause = min(
                self._longest_pause, self._first_pause * 2 ** (self._failures - 1)
            )
            self._paused_until = self._clock() + pause
