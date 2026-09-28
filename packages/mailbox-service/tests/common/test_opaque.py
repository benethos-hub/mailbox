"""Opaque values, and base64 without padding."""

from __future__ import annotations

import pytest

from benethos_mailbox_service.common.opaque import (
    decode,
    encode,
    from_base64,
    to_base64,
)


def test_a_value_round_trips_under_its_prefix() -> None:
    token = encode("cur_", ["2026-09-28", "snd_1"])
    assert token.startswith("cur_") and "=" not in token
    assert decode("cur_", token) == ["2026-09-28", "snd_1"]


@pytest.mark.parametrize("token", ["other_abc", "cur_!!!", "cur_bm90IGpzb24"])
def test_anything_else_is_refused(token: str) -> None:
    with pytest.raises(ValueError, match="not a cur_ value"):
        decode("cur_", token)


def test_base64_without_padding_in_both_alphabets() -> None:
    data = bytes([0xFB, 0xFF, 0xBF])
    assert to_base64(data) == "-_-_"
    assert to_base64(data, url=False) == "+/+/"
    assert to_base64(b"a") == "YQ"
    assert from_base64("YQ") == b"a"
    assert from_base64("+/+/", url=False) == data
    with pytest.raises(ValueError):
        from_base64("a*b")
