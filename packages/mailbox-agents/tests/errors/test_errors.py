"""The error hierarchy, and its texts masked."""

from __future__ import annotations

from benethos_mailbox_agents import errors
from benethos_mailbox_common.log import redact


def test_an_error_is_redacted_on_construction() -> None:
    redact.note("gateway-key-123")

    raised = errors.GatewayUnavailableError("calling with gateway-key-123 failed")

    assert "gateway-key-123" not in str(raised)
    assert raised.message == "calling with *** failed"


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
