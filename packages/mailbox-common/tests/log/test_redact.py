"""Secrets noted once are masked in every text."""

from __future__ import annotations

import pytest

from benethos_mailbox_common.log import redact

PASSWORD = "hunter2-but-longer"


def test_a_noted_secret_is_masked() -> None:
    redact.note(PASSWORD)
    assert redact.redact(f"LOGIN me {PASSWORD} refused") == "LOGIN me *** refused"


def test_a_short_value_is_not_masked() -> None:
    """A password "abc" would hide every "abc" of the log."""
    redact.note("abc")
    assert redact.redact("abc def") == "abc def"


def test_the_longest_secret_goes_first() -> None:
    redact.note("token-part")
    redact.note("token-part-and-more")
    assert redact.redact("got token-part-and-more") == "got ***"


def test_only_the_newest_are_kept(monkeypatch: pytest.MonkeyPatch) -> None:
    monkeypatch.setattr(redact, "KEPT", 2)
    for secret in ("first-secret", "second-secret", "third-secret"):
        redact.note(secret)
    assert redact.redact("first-secret third-secret") == "first-secret ***"
