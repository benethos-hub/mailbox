"""Ids of the service's own records."""

from __future__ import annotations

import re

from benethos_mailbox_api.common.ids import new_id


def test_an_id_is_the_prefix_and_64_hex_digits() -> None:
    assert re.fullmatch(r"acc_[0-9a-f]{64}", new_id("acc"))


def test_ids_do_not_repeat() -> None:
    assert len({new_id("msg") for _ in range(1000)}) == 1000
