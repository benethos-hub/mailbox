"""Tables in memory with a cap."""

from __future__ import annotations

from benethos_mailbox_service.domain.bounded import trim


def test_what_no_longer_counts_goes_first_then_the_oldest() -> None:
    table = {"a": 5, "b": 1, "c": 9, "d": 3}
    dropped: list[str] = []
    trim(table, 2, gone=lambda v: v < 2, age=lambda v: v, dropped=dropped.append)
    assert table == {"a": 5, "c": 9}
    assert dropped == ["b", "d"]


def test_a_table_within_its_cap_stays_as_it_is() -> None:
    table = {"a": 0}
    trim(table, 1, gone=lambda v: True, age=lambda v: v)
    assert table == {"a": 0}
