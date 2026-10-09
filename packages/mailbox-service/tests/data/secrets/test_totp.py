"""Time-based one-time passwords (docs/AUTHENTICATION.md 2)."""

from __future__ import annotations

import base64
from datetime import UTC, datetime, timedelta
from urllib.parse import parse_qs, urlsplit

import pytest

from benethos_mailbox_service.data.secrets import totp

# The secret of the test vectors in RFC 6238, appendix B, for SHA-1.
RFC_SECRET = b"12345678901234567890"


@pytest.mark.parametrize(
    ("seconds", "expected"),
    [
        (59, "287082"),
        (1111111109, "081804"),
        (1111111111, "050471"),
        (1234567890, "005924"),
        (2000000000, "279037"),
        (20000000000, "353130"),
    ],
)
def test_the_codes_of_rfc_6238(seconds: int, expected: str) -> None:
    """The last six digits of the RFC's eight."""
    at = datetime.fromtimestamp(seconds, UTC)
    assert totp.code(RFC_SECRET, totp.step_of(at)) == expected


def test_a_new_secret_is_random_and_long_enough() -> None:
    first, second = totp.new_secret(), totp.new_secret()
    assert len(first) == 20 and first != second


def test_the_secret_is_written_in_base32_without_padding() -> None:
    written = totp.base32(RFC_SECRET)
    assert "=" not in written
    assert base64.b32decode(written) == RFC_SECRET
    assert totp.from_base32(written) == RFC_SECRET
    secret = totp.new_secret()
    assert totp.from_base32(totp.base32(secret)) == secret


NOW = datetime(2026, 10, 9, 12, 0, 10, tzinfo=UTC)


def test_the_current_code_matches_its_step() -> None:
    step = totp.step_of(NOW)
    assert totp.matching_step(RFC_SECRET, totp.code(RFC_SECRET, step), NOW) == step


@pytest.mark.parametrize("shift", [-1, 1])
def test_a_step_either_way_is_taken(shift: int) -> None:
    step = totp.step_of(NOW) + shift
    assert totp.matching_step(RFC_SECRET, totp.code(RFC_SECRET, step), NOW) == step


@pytest.mark.parametrize("shift", [-2, 2])
def test_two_steps_off_is_refused(shift: int) -> None:
    step = totp.step_of(NOW) + shift
    assert totp.matching_step(RFC_SECRET, totp.code(RFC_SECRET, step), NOW) is None


def test_a_code_works_once() -> None:
    step = totp.step_of(NOW)
    presented = totp.code(RFC_SECRET, step)
    assert totp.matching_step(RFC_SECRET, presented, NOW, after=step) is None
    later = NOW + timedelta(seconds=totp.STEP_SECONDS)
    # The next step's code still works after the last one taken.
    following = totp.code(RFC_SECRET, step + 1)
    assert totp.matching_step(RFC_SECRET, following, later, after=step) == step + 1


@pytest.mark.parametrize("presented", ["", "12345", "1234567", "12a456", "abcdef"])
def test_anything_but_six_digits_is_refused(presented: str) -> None:
    assert totp.matching_step(RFC_SECRET, presented, NOW) is None


def test_spaces_around_a_code_do_not_count() -> None:
    step = totp.step_of(NOW)
    presented = f" {totp.code(RFC_SECRET, step)} "
    assert totp.matching_step(RFC_SECRET, presented, NOW) == step


def test_the_uri_names_issuer_account_and_secret() -> None:
    uri = totp.uri(RFC_SECRET, "Mailbox", "anna@mail.example.org")
    parts = urlsplit(uri)
    assert parts.scheme == "otpauth" and parts.netloc == "totp"
    assert parts.path == "/Mailbox:anna@mail.example.org"
    query = parse_qs(parts.query)
    assert query == {
        "secret": [totp.base32(RFC_SECRET)],
        "issuer": ["Mailbox"],
        "algorithm": ["SHA1"],
        "digits": ["6"],
        "period": ["30"],
    }


def test_the_uri_quotes_what_a_label_cannot_hold() -> None:
    uri = totp.uri(RFC_SECRET, "Mailbox", "Anna Maria/ops?")
    assert "/Mailbox:Anna%20Maria%2Fops%3F?" in uri
