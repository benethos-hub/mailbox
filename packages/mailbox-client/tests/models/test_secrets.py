"""A secret the service shows once: readable on purpose, never by
accident in a line."""

from __future__ import annotations

from benethos_mailbox_client import Secret


def test_a_secret_shows_in_no_line() -> None:
    secret = Secret("whsec_value")
    assert secret.get_secret_value() == "whsec_value"
    assert "whsec_value" not in repr(secret) and "whsec_value" not in str(secret)
    assert "whsec_value" not in f"{secret}" and "whsec_value" not in repr([secret])


def test_secrets_compare_by_their_value() -> None:
    assert Secret("a") == Secret("a") and Secret("a") != Secret("b")
    assert Secret("a") != "a"
    assert len({Secret("a"), Secret("a")}) == 1
