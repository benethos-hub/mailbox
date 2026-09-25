"""Pacing towards one provider account: a token bucket and a backoff.

Clock, sleep and randomness are injectable, so tests run without waiting.
"""

from __future__ import annotations

import random
import time
from collections.abc import Callable

Clock = Callable[[], float]
Sleep = Callable[[float], None]


class TokenBucket:
    """At most ``per_minute`` requests a minute, bursts up to ``burst``."""

    def __init__(
        self,
        per_minute: float,
        burst: int,
        clock: Clock = time.monotonic,
        sleep: Sleep = time.sleep,
    ) -> None:
        if per_minute <= 0 or burst < 1:
            raise ValueError("the rate and the burst must be positive")
        self._rate = per_minute / 60.0
        self._burst = float(burst)
        self._tokens = float(burst)
        self._clock = clock
        self._sleep = sleep
        self._last = clock()

    def acquire(self) -> None:
        """Take one token, waiting for it if the bucket is empty."""
        self._refill()
        if self._tokens < 1:
            self._sleep((1 - self._tokens) / self._rate)
            self._refill()
        self._tokens -= 1

    def _refill(self) -> None:
        now = self._clock()
        self._tokens = min(self._burst, self._tokens + (now - self._last) * self._rate)
        self._last = now


def backoff(
    attempt: int,
    base: float = 0.5,
    cap: float = 900.0,
    jitter: Callable[[float, float], float] = random.uniform,
) -> float:
    """Seconds to wait before retry ``attempt`` (0-based): exponential, with
    full jitter so that many accounts do not retry in step."""
    return jitter(0.0, min(cap, base * 2**attempt))
