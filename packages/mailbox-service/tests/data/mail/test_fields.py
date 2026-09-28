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
