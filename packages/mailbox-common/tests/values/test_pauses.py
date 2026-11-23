"""Pauses that double."""

from __future__ import annotations

from benethos_mailbox_common.values.pauses import doubled


def test_a_pause_doubles_up_to_the_ceiling() -> None:
    assert doubled(1.0, 0, 10.0) == 1.0
    assert [doubled(60.0, n, 900.0) for n in range(5)] == [
        60.0,
        120.0,
        240.0,
        480.0,
        900.0,
    ]


def test_a_count_that_grew_for_weeks_stays_a_number() -> None:
    assert doubled(60.0, 5000, 900.0) == 900.0


def test_a_negative_count_is_the_first_pause() -> None:
    assert doubled(60.0, -3, 900.0) == 60.0
