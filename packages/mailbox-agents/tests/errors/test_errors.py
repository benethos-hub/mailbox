"""The error hierarchy and redact."""

from __future__ import annotations

from collections.abc import Iterator

import pytest

from benethos_mailbox_agents import errors


@pytest.fixture(autouse=True)
def _no_secrets() -> Iterator[None]:
    errors.forget_secrets()
    yield
    errors.forget_secrets()


def test_redact_replaces_a_registered_secret() -> None:
    errors.register_secret("s3cret-token")

    assert errors.redact("token s3cret-token refused") == "token [redacted] refused"


def test_redact_replaces_the_longer_secret_whole() -> None:
    errors.register_secret("abcdef")
    errors.register_secret("abcdefghij")

    assert errors.redact("x abcdefghij y") == "x [redacted] y"


@pytest.mark.parametrize("secret", [None, "", "short"])
def test_a_short_or_missing_secret_is_not_registered(secret: str | None) -> None:
    errors.register_secret(secret)

    assert errors.redact("short and sweet") == "short and sweet"


def test_an_error_is_redacted_on_construction() -> None:
    errors.register_secret("gateway-key-123")

    raised = errors.GatewayUnavailableError("calling with gateway-key-123 failed")

    assert "gateway-key-123" not in str(raised)
    assert raised.message == "calling with [redacted] failed"


def test_every_error_derives_from_the_base() -> None:
    for name in errors.__all__:
        found = getattr(errors, name)
        if isinstance(found, type):
            assert issubclass(found, errors.MailboxAgentError)


def test_the_unavailable_kinds_share_a_base() -> None:
    assert issubclass(errors.MailboxUnavailableError, errors.UnavailableError)
    assert issubclass(errors.GatewayUnavailableError, errors.UnavailableError)


def test_refusals_carry_what_a_log_line_may_say() -> None:
    refused = errors.MailboxRefusedError("no", status=403, reason="forbidden")
    answer = errors.AnswerRefusedError("bad", reason="schema")

    assert (refused.status, refused.reason, refused.code) == (
        403,
        "forbidden",
        "mailbox_refused",
    )
    assert (answer.reason, answer.code) == ("schema", "answer_refused")
