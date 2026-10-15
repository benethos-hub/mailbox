"""Care towards one account's server: retries, pauses, rejected logins."""

from __future__ import annotations

import pytest

from benethos_mailbox_service.data.providers.guard import Guard
from benethos_mailbox_service.errors import (
    ProviderAuthError,
    ProviderError,
    ProviderUnavailableError,
)

from ...clocks import Seconds


def guard(
    time: Seconds, first_pause: float = 30.0, longest_pause: float = 900.0
) -> Guard:
    """A guard with room for every request, on ``time``."""
    return Guard(
        6000,
        clock=time,
        sleep=time.sleep,
        jitter=lambda low, high: high,
        first_pause=first_pause,
        longest_pause=longest_pause,
    )


class Steps:
    """A step that fails as it is told, in turn, then answers."""

    def __init__(self, *failures: Exception) -> None:
        self.failures = list(failures)
        self.runs = 0
        self.dropped = 0

    def step(self) -> str:
        self.runs += 1
        if self.failures:
            raise self.failures.pop(0)
        return "done"

    def drop(self) -> None:
        self.dropped += 1


def down() -> ProviderUnavailableError:
    return ProviderUnavailableError("no answer")


def test_an_unreachable_server_is_tried_again() -> None:
    time = Seconds()
    steps = Steps(down(), down())
    assert guard(time).attempts(steps.step, steps.drop) == "done"
    assert steps.runs == 3
    assert steps.dropped == 2
    assert len(time.sleeps) == 2


def test_after_the_last_attempt_the_server_rests_longer_each_time() -> None:
    time = Seconds()
    watched = guard(time, first_pause=30, longest_pause=50)
    for pause in (30, 50, 50):
        steps = Steps(down(), down(), down())
        with pytest.raises(ProviderUnavailableError):
            watched.attempts(steps.step, steps.drop)
        with pytest.raises(ProviderUnavailableError, match="next attempt"):
            watched.check()
        time.now += pause - 1
        with pytest.raises(ProviderUnavailableError):
            watched.check()
        time.now += 1
        watched.check()


def test_another_failure_is_not_tried_again() -> None:
    time = Seconds()
    steps = Steps(ProviderError("refused"))
    with pytest.raises(ProviderError, match="refused"):
        guard(time).attempts(steps.step, steps.drop)
    assert (steps.runs, steps.dropped) == (1, 1)


def test_a_rejected_login_blocks_until_reset() -> None:
    time = Seconds()
    watched = guard(time)
    steps = Steps(ProviderAuthError("wrong password"))
    with pytest.raises(ProviderAuthError):
        watched.attempts(steps.step, steps.drop)
    with pytest.raises(ProviderAuthError, match="rejected the login before"):
        watched.once(lambda: "sent")
    assert steps.runs == 1
    watched.reset()
    assert watched.once(lambda: "sent") == "sent"


def test_once_runs_while_the_server_rests() -> None:
    """A send over SMTP may reach another server than the resting one."""
    time = Seconds()
    watched = guard(time)
    steps = Steps(down(), down(), down())
    with pytest.raises(ProviderUnavailableError):
        watched.attempts(steps.step, steps.drop)
    assert watched.once(lambda: "sent") == "sent"
