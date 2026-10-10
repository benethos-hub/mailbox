"""Sizes in bytes."""

from __future__ import annotations

from benethos_mailbox_common.values.sizes import MIB, megabytes


def test_megabytes_are_whole() -> None:
    assert megabytes(25 * MIB) == "25 MB"
    assert megabytes(25 * MIB + MIB - 1) == "25 MB"
    assert megabytes(0) == "0 MB"
