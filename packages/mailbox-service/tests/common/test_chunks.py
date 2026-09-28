"""A sequence in slices."""

from __future__ import annotations

import pytest

from benethos_mailbox_service.common.chunks import batched


def test_slices_keep_the_type_and_the_last_is_shorter() -> None:
    assert list(batched([1, 2, 3, 4, 5], 2)) == [[1, 2], [3, 4], [5]]
    assert list(batched("ABCDEFG", 4)) == ["ABCD", "EFG"]
    assert list(batched([], 3)) == []


def test_a_batch_holds_one_value_at_least() -> None:
    with pytest.raises(ValueError, match="one value"):
        list(batched([1], 0))
