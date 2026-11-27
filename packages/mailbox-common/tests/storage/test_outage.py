"""A database server away, as its place keeps it: every call fails at
once until the next attempt is due, the pause doubles from one second to
thirty, and the server answering again ends it."""

from __future__ import annotations

from benethos_mailbox_common.storage.outage import Outage

from .clocks import Seconds


def test_a_server_that_answers_is_not_away() -> None:
    outage = Outage(Seconds())
    assert not outage.away
    assert outage.mended() is None


def test_the_pause_doubles_up_to_thirty_seconds() -> None:
    clock = Seconds()
    outage = Outage(clock)
    pauses = []
    went = []
    for _ in range(8):
        went.append(outage.failed("OperationalError (08006)"))
        pauses.append(outage.unavailable().retry_after)
        assert not outage.due()
        clock.now += pauses[-1]
        assert outage.due()
    assert went == [True] + [False] * 7
    assert pauses == [1, 2, 4, 8, 16, 30, 30, 30]


def test_while_away_the_error_says_the_seconds_left_and_the_cause() -> None:
    clock = Seconds()
    outage = Outage(clock)
    outage.failed("OperationalError (08006)")
    outage.failed("OperationalError (08001)")
    clock.now += 0.5
    error = outage.unavailable()
    assert error.retry_after == 2
    assert error.cause == "OperationalError (08001)"
    assert "08001" not in str(error)


def test_the_server_back_ends_it_and_says_how_long() -> None:
    clock = Seconds()
    outage = Outage(clock)
    outage.failed("OperationalError (08006)")
    clock.now += 1
    outage.failed("OperationalError (08006)")
    clock.now += 2.5
    assert outage.mended() == 3.5
    assert not outage.away
    assert outage.due()
    assert outage.failed("OperationalError (08006)") is True
    assert outage.unavailable().retry_after == 1
