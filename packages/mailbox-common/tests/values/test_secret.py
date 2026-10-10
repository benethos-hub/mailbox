"""Ids, tokens, digests and signatures."""

from __future__ import annotations

import re

from benethos_mailbox_common.values.secret import (
    SHORT,
    digest,
    hmac_hex,
    new_id,
    same,
    token,
)


def test_an_id_is_the_prefix_and_64_hex_digits() -> None:
    assert re.fullmatch(r"acc_[0-9a-f]{64}", new_id("acc"))


def test_ids_do_not_repeat() -> None:
    assert len({new_id("msg") for _ in range(1000)}) == 1000


def test_a_token_is_url_safe_and_as_long_as_asked() -> None:
    assert re.fullmatch(r"[A-Za-z0-9_-]{43}", token())
    assert re.fullmatch(r"[A-Za-z0-9_-]{32}", token(SHORT))


def test_a_digest_and_a_signature() -> None:
    assert digest("abc") == (
        "ba7816bf8f01cfea414140de5dae2223b00361a396177a9cb410ff61f20015ad"
    )
    assert hmac_hex("key", b"data") == (
        "5031fe3d989c6d1537a013fa6e739da23463fdaec3b70137d828e36ace221bd0"
    )


def test_same_compares_whole_values() -> None:
    assert same("a-secret", "a-secret")
    assert not same("a-secret", "a-secreT")
    assert not same("a", "a-secret")
