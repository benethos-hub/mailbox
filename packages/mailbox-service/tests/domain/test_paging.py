"""The cursors the service hands out, and the page they continue."""

from __future__ import annotations

import pytest

from benethos_mailbox_service.domain.paging import (
    Order,
    decode_cursor,
    encode_cursor,
    page,
    split_page,
)
from benethos_mailbox_service.errors import BadRequestError


def test_a_cursor_carries_its_value_back() -> None:
    assert decode_cursor("c_", encode_cursor("c_", [1, "a"])) == [1, "a"]
    assert decode_cursor("c_", encode_cursor("c_", "7"), int) == 7


@pytest.mark.parametrize("cursor", ["other_abc", "c_!!!", encode_cursor("c_", "x")])
def test_a_cursor_not_ours_or_not_readable_is_a_bad_request(cursor: str) -> None:
    with pytest.raises(BadRequestError, match="invalid cursor"):
        decode_cursor("c_", cursor, int)


def test_the_refusal_can_be_named() -> None:
    with pytest.raises(BadRequestError, match="not a state"):
        decode_cursor("c_", "nope", refusal="not a state")


def test_a_page_and_whether_there_is_more() -> None:
    assert split_page([1, 2, 3], 2) == ([1, 2], True)
    assert split_page([1, 2], 2) == ([1, 2], False)


BY_NAME = Order[tuple[str, str]]("n_", lambda item: (item[0].casefold(), item[1]))
ITEMS = [("bob", "2"), ("Anna", "3"), ("anna", "1"), ("Carl", "4")]


def pages(items: list[tuple[str, str]], limit: int) -> list[list[str]]:
    """The ids of every page, following the cursors."""
    found: list[list[str]] = []
    cursor = None
    while True:
        one = page(items, BY_NAME, limit=limit, cursor=cursor)
        found.append([item[1] for item in one.items])
        if one.next_cursor is None:
            return found
        cursor = one.next_cursor


def test_a_list_held_whole_pages_in_its_order() -> None:
    assert pages(ITEMS, 2) == [["1", "3"], ["2", "4"]]
    assert pages(ITEMS, 4) == [["1", "3", "2", "4"]]
    assert pages([], 2) == [[]]


def test_the_next_page_does_not_shift_when_the_list_changes() -> None:
    first = page(ITEMS, BY_NAME, limit=2, cursor=None)
    changed = [*ITEMS[1:], ("Aaron", "5"), ("Bert", "6")]  # bob gone, two new
    after = page(changed, BY_NAME, limit=2, cursor=first.next_cursor)
    assert [item[1] for item in after.items] == ["6", "4"]


@pytest.mark.parametrize(
    "cursor",
    [
        encode_cursor("other_", ["anna", "1"]),
        encode_cursor("n_", "anna"),
        encode_cursor("n_", [True]),
        encode_cursor("n_", [1, 2]),  # numbers where the order has text
    ],
)
def test_a_cursor_of_another_list_is_a_bad_request(cursor: str) -> None:
    with pytest.raises(BadRequestError, match="invalid cursor"):
        page(ITEMS, BY_NAME, limit=2, cursor=cursor)
