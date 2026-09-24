from __future__ import annotations

import pytest

from benethos_mailbox_api.data.providers.ratelimit import TokenBucket, backoff


class Time:
    def __init__(self) -> None:
        self.now = 0.0
        self.sleeps: list[float] = []

    def clock(self) -> float:
        return self.now

    def sleep(self, seconds: float) -> None:
        self.sleeps.append(seconds)
        self.now += seconds


def test_burst_then_steady_rate() -> None:
    t = Time()
    bucket = TokenBucket(per_minute=120, burst=3, clock=t.clock, sleep=t.sleep)
    for _ in range(3):
        bucket.acquire()
    assert t.sleeps == []
    bucket.acquire()
    assert t.sleeps == [pytest.approx(0.5)]


def test_refills_over_time_up_to_the_burst() -> None:
    t = Time()
    bucket = TokenBucket(per_minute=60, burst=2, clock=t.clock, sleep=t.sleep)
    bucket.acquire()
    bucket.acquire()
    t.now += 10
    bucket.acquire()
    bucket.acquire()
    assert t.sleeps == []
    bucket.acquire()
    assert t.sleeps == [pytest.approx(1.0)]


@pytest.mark.parametrize(("per_minute", "burst"), [(0, 1), (10, 0)])
def test_rejects_nonsense(per_minute: float, burst: int) -> None:
    with pytest.raises(ValueError):
        TokenBucket(per_minute, burst)


def test_backoff_grows_and_is_capped() -> None:
    def top(low: float, high: float) -> float:
        return high

    assert [backoff(n, jitter=top) for n in range(4)] == [0.5, 1.0, 2.0, 4.0]
    assert backoff(30, jitter=top) == 900.0
    assert 0.0 <= backoff(3) <= 4.0
