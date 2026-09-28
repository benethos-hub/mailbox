"""The cursors the service hands out, and the page they continue."""

from __future__ import annotations

import pytest

from benethos_mailbox_service.domain.paging import (
    decode_cursor,
    encode_cursor,
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
