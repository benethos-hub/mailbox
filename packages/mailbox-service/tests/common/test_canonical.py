"""A value as JSON, one way for what goes on and one for a hash."""

from __future__ import annotations

import json

from benethos_mailbox_service.common.canonical import canonical, compact


def test_compact_keeps_the_text_and_the_order() -> None:
    value = {"b": "Grüße", "a": [1, 2]}
    assert compact(value) == '{"b":"Grüße","a":[1,2]}'
    assert json.loads(compact(value)) == value


def test_canonical_is_the_same_for_the_same_value() -> None:
    one = canonical({"b": "Grüße", "a": [1, 2]})
    assert one == canonical({"a": [1, 2], "b": "Grüße"})
    assert one == '{"a":[1,2],"b":"Gr\\u00fc\\u00dfe"}'
    assert one.isascii()
