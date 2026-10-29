"""An address as people read it."""

from __future__ import annotations

from email.utils import getaddresses

import pytest

from benethos_mailbox_common.mail.addresses import Parsed, parsed, readable


def test_a_name_and_an_email() -> None:
    assert readable("Ann Smith", "ann@example.org") == "Ann Smith <ann@example.org>"


@pytest.mark.parametrize("name", [None, ""])
def test_without_a_name_the_email_alone(name: str | None) -> None:
    assert readable(name, "ann@example.org") == "ann@example.org"
    assert readable(name, "ann@example.org", quoted=True) == "ann@example.org"


def test_quoted_puts_the_name_in_quotes() -> None:
    assert readable("Ann", "ann@example.org", quoted=True) == '"Ann" <ann@example.org>'


@pytest.mark.parametrize(
    "name",
    ["Smith, Ann", 'Ann "Bo" Smith', r"C:\Ann", 'a\\"b', "Zoë Ågren"],
)
def test_a_quoted_name_comes_back_as_it_was(name: str) -> None:
    """A form shows the addresses quoted and reads them back with
    ``getaddresses``."""
    text = ", ".join(
        [readable(name, "ann@example.org", quoted=True), "bob@example.org"]
    )
    assert getaddresses([text]) == [(name, "ann@example.org"), ("", "bob@example.org")]


def test_typed_addresses_are_split_by_comma_or_semicolon() -> None:
    typed = parsed(
        ' Ann <ann@example.org>; b@example.org, "Smith, Ann" <s@example.org> '
    )
    assert typed == [
        Parsed("Ann", "ann@example.org"),
        Parsed(None, "b@example.org"),
        Parsed("Smith, Ann", "s@example.org"),
    ]


@pytest.mark.parametrize("text", ["", "  "])
def test_nothing_typed_is_no_address(text: str) -> None:
    assert parsed(text) == []


def test_what_is_typed_is_not_judged() -> None:
    assert parsed("nonsense") == [Parsed(None, "nonsense")]
