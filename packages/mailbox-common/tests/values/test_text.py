"""Text on one line, for a reader and for the wire, and counted in words."""

from __future__ import annotations

import unicodedata

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


@pytest.mark.parametrize(
    ("value", "written"),
    [
        ("\x9b", "\\x9b"),
        ("\x85", "\\x85"),
        ("‮", "\\u202e"),
        ("⁦", "\\u2066"),
        ("؜", "\\u061c"),
        ("\ud800", "\\ud800"),
    ],
)
def test_escaped_writes_c1_direction_and_a_lone_surrogate_as_escapes(
    value: str, written: str
) -> None:
    assert escaped(f"a{value}b") == f"a{written}b"


# The marks that turn the direction of the text after them.
_DIRECTION = frozenset(
    map(chr, (0x061C, 0x200E, 0x200F, *range(0x202A, 0x202F), *range(0x2066, 0x206A)))
)


def test_escaped_writes_exactly_the_controls_separators_marks_and_surrogates() -> None:
    """The rule by Unicode's own categories: control, line and paragraph
    separator, surrogate, and the marks of direction. Checked over every
    code point."""
    for code in range(0x110000):
        char = chr(code)
        unsafe = (
            unicodedata.category(char) in {"Cc", "Zl", "Zp", "Cs"} or char in _DIRECTION
        )
        assert (escaped(char) != char) is unsafe, hex(code)


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
