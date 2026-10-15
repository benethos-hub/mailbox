"""One header field, as this project writes it."""

from __future__ import annotations

import pytest

from benethos_mailbox_service.data.mail import fields
from benethos_mailbox_service.errors import BadRequestError


def test_an_address_on_the_wire_has_its_domain_in_punycode() -> None:
    assert fields.wire_address("mü@bücher.de") == "mü@xn--bcher-kva.de"
    assert fields.wire_address("me@example.com") == "me@example.com"


def test_a_domain_idna_cannot_write_is_a_bad_request() -> None:
    with pytest.raises(BadRequestError, match="cannot be encoded"):
        fields.wire_address("me@bücher..de")


@pytest.mark.parametrize(
    ("header", "found"),
    [
        ("<a@example.org>", "<a@example.org>"),
        ("<a@exam\r\n ple.org>", "<a@example.org>"),
        ("<a@example.org> (Alice's mail of Monday)", "<a@example.org>"),
        ("Alice's mail <a@example.org>", "<a@example.org>"),
        ("a@example.org", "a@example.org"),
        ("", None),
    ],
)
def test_one_message_id(header: str, found: str | None) -> None:
    assert fields.message_id(header) == found


@pytest.mark.parametrize(
    ("header", "found"),
    [
        ("<a@x.org> <b@x.org>", ["<a@x.org>", "<b@x.org>"]),
        ("<a@x.org>\r\n <b@x.org>", ["<a@x.org>", "<b@x.org>"]),
        ("<a@x.org><b@x.org>", ["<a@x.org>", "<b@x.org>"]),
        ("<a@x.org> (comment) <b@x\r\n .org>", ["<a@x.org>", "<b@x.org>"]),
        ("a@x.org b@x.org", ["a@x.org", "b@x.org"]),
        (None, []),
    ],
)
def test_message_ids_of_a_list(header: str | None, found: list[str]) -> None:
    assert fields.message_ids(header) == found
