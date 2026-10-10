"""Text on one line, for a reader and for the wire, and counted in words."""

from __future__ import annotations

import pytest

from benethos_mailbox_common.values.text import (
    ends_line,
    escaped,
    has_break,
    joined,
    plural,
)

# Every character ``str.splitlines`` breaks on, and the other controls.
READER_BREAKS = ["\n", "\r", "\x0b", "\x0c", "\x1c", "\x85", "\u2028", "\u2029"]
CONTROLS = ["\x00", "\x01", "\x1b", "\x7f", "\t"]


@pytest.mark.parametrize("value", READER_BREAKS + CONTROLS)
def test_a_reader_sees_every_break_and_control(value: str) -> None:
    text = f"a{value}b"
    assert has_break(text)
    assert not has_break(escaped(text))
    assert joined(text) == "a b"


def test_escaped_writes_the_break_as_its_escape() -> None:
    assert escaped("evil\nINFO forged") == "evil\\nINFO forged"
    assert escaped("plain text, with ümlauts") == "plain text, with ümlauts"


def test_joined_makes_one_space_of_a_run() -> None:
    assert joined("Re:\r\n  next") == "Re:   next"
    assert joined("one\n\n\ntwo") == "one two"


@pytest.mark.parametrize("value", ["\r", "\n", "\x00"])
def test_the_wire_ends_a_line_at_cr_lf_and_nul(value: str) -> None:
    assert ends_line("fine", f"a{value}b")


@pytest.mark.parametrize("value", ["\x85", "\u2028", "\t", "\x01", '"'])
def test_the_wire_carries_the_rest_as_data(value: str) -> None:
    assert not ends_line(f"a{value}b")


def test_plural() -> None:
    assert plural(0, "record") == "0 records"
    assert plural(1, "record") == "1 record"
    assert plural(2, "record") == "2 records"
