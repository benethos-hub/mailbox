"""Lists across accounts: the merge order, the positions, their cursor and
one step on every account."""

from __future__ import annotations

from datetime import UTC, datetime, timedelta

import pytest

from benethos_mailbox_service.data.models import AccountFailure, MessageSummary
from benethos_mailbox_service.domain.mailbox.merge import (
    Chunk,
    Position,
    Positions,
    advance,
    decode_cursor,
    encode_cursor,
    newest_of,
    per_account,
)
from benethos_mailbox_service.errors import BadRequestError, ProviderUnavailableError

START = datetime(2026, 9, 1, tzinfo=UTC)


def at(hour: int, name: str) -> MessageSummary:
    return MessageSummary(id=name, received=START + timedelta(hours=hour))


def chunk(*items: MessageSummary, next_cursor: str | None = None) -> Chunk:
    return Chunk(cursor=None, offset=0, items=list(items), next_cursor=next_cursor)


def test_the_newest_of_every_account_first() -> None:
    windows = {
        "acc_a": [chunk(at(9, "a9"), at(5, "a5"))],
        "acc_b": [chunk(at(7, "b7"), at(1, "b1"))],
    }
    taken = newest_of(windows, 3)
    assert [(item.id, account) for item, account in taken] == [
        ("a9", "acc_a"),
        ("b7", "acc_b"),
        ("a5", "acc_a"),
    ]


def test_an_account_is_taken_in_its_own_order() -> None:
    """IMAP gives messages by arrival: one filed late with an old date
    stays where the account put it, so nothing after it is skipped."""
    windows = {"acc_a": [chunk(at(9, "a9"), at(1, "late"), at(8, "a8"))]}
    taken = [item.id for item, _ in newest_of(windows, 2)]
    assert taken == ["a9", "late"]


def test_the_position_after_what_was_handed_out() -> None:
    start = Position("all", None, 0)
    window = [
        Chunk(cursor=None, offset=0, items=[at(3, "x"), at(2, "y")], next_cursor="c2"),
        Chunk(cursor="c2", offset=0, items=[at(1, "z")], next_cursor="c3"),
    ]
    assert advance(start, window, 1) == Position("all", None, 1)
    assert advance(start, window, 2) == Position("all", "c2", 0)
    assert advance(start, window, 3) == Position("all", "c3", 0)
    window[-1].next_cursor = None
    assert advance(start, window, 3) == Position("all", None, 0, done=True)


def test_the_cursor_carries_positions_and_size() -> None:
    positions = Positions(
        {
            "acc_a": Position("inbox", "c1", 2),
            "acc_b": Position("inbox", None, 0, True),
        },
        25,
    )
    assert decode_cursor(encode_cursor(positions, "q1"), "q1") == positions


def test_a_cursor_of_another_search_is_refused() -> None:
    cursor = encode_cursor(Positions({}, 10), "q1")
    with pytest.raises(BadRequestError, match="another search"):
        decode_cursor(cursor, "q2")


def test_a_cursor_without_a_size_is_refused() -> None:
    cursor = encode_cursor(Positions({}, 0), "q1")
    with pytest.raises(BadRequestError):
        decode_cursor(cursor, "q1")


async def test_an_account_that_fails_leaves_the_others() -> None:
    async def run(account_id: str) -> str:
        if account_id == "acc_b":
            raise ProviderUnavailableError("down")
        return account_id.upper()

    failures: list[AccountFailure] = []
    results = await per_account(["acc_a", "acc_b", "acc_c"], run, failures)
    assert results == {"acc_a": "ACC_A", "acc_c": "ACC_C"}
    assert [(f.account_id, f.code) for f in failures] == [
        ("acc_b", "provider_unavailable")
    ]
