"""JSON read into shapes at the edge: odd fields, nulls, and a failure
that names nothing of the input."""

from __future__ import annotations

from typing import Annotated

import pytest

from benethos_mailbox_service.data.protocols import wire
from benethos_mailbox_service.errors import ProviderError


class Answer(wire.CamelShape):
    access_id: str
    lifetime: wire.Seconds = None
    note: Annotated[str | None, wire.OrNone] = None
    tags: list[str] = []


def test_fields_in_camel_case_and_extra_ones_passed_by() -> None:
    found = wire.parse(Answer, b'{"accessId": "a", "more": 1}', "odd")
    assert found == Answer(access_id="a")


def test_null_counts_as_left_out() -> None:
    found = wire.parse(Answer, b'{"accessId": "a", "tags": null}', "odd")
    assert found.tags == []


@pytest.mark.parametrize(
    ("value", "seconds"),
    [(60, 60), ('"60"', 60), (0, None), ('"soon"', None), ("true", None)],
)
def test_seconds_as_a_server_writes_them(value: object, seconds: int | None) -> None:
    found = wire.parse(Answer, f'{{"accessId": "a", "lifetime": {value}}}', "odd")
    assert found.lifetime == seconds


def test_an_odd_field_does_not_spoil_the_answer() -> None:
    assert wire.parse(Answer, b'{"accessId": "a", "note": [1]}', "odd").note is None


def test_a_failure_names_nothing_of_the_input() -> None:
    with pytest.raises(ProviderError) as exc:
        wire.parse(Answer, b'{"accessId": ["secret-token"]}', "the answer is odd")
    assert str(exc.value) == "the answer is odd"
    assert exc.value.__cause__ is None and exc.value.__suppress_context__


def test_read_answers_none_for_another_shape() -> None:
    assert wire.read(Answer, b"<html>") is None
    assert wire.read(Answer, b'{"accessId": "a"}') == Answer(access_id="a")


def test_values_decoded_already() -> None:
    assert wire.parse_value(Answer, {"accessId": "a"}, "odd") == Answer(access_id="a")
    with pytest.raises(ProviderError, match="^odd$"):
        wire.parse_value(Answer, {"accessId": None}, "odd")
    assert wire.read_value(Answer, ["no object"]) is None
