"""The records passed between the layers."""

from __future__ import annotations

from datetime import UTC, datetime

import pytest
from pydantic import ValidationError

from benethos_mailbox_agents.records import (
    LABEL,
    Address,
    Decision,
    Evidence,
    FolderRef,
    MailMessage,
    MessageRef,
    StepResult,
)

REF = MessageRef(account_id="a1", message_id="m1")


def test_a_domain_is_lower_case_after_the_last_at() -> None:
    assert Address(email='"x@y"@Billing.Example.TEST').domain == "billing.example.test"


def test_a_message_knows_its_folder_roles() -> None:
    message = MailMessage(
        ref=REF,
        folders=(FolderRef(id="f1", name="INBOX", role="inbox", path="INBOX"),),
    )

    assert message.in_role("inbox")
    assert not message.in_role("sent")


def test_a_keyword_is_found_in_any_case() -> None:
    message = MailMessage(ref=REF, keywords=("agent-x",))

    assert message.has_keyword("Agent-X")
    assert not message.has_keyword("agent-y")


def test_records_are_frozen_and_strict() -> None:
    with pytest.raises(ValidationError):
        REF.message_id = "m2"  # type: ignore[misc]
    with pytest.raises(ValidationError):
        MessageRef(account_id="a", message_id="m", subject="x")  # type: ignore[call-arg]


def test_a_decision_is_actionable_unless_refused() -> None:
    evidence = Evidence(field=LABEL, value="invoice", quote="Your invoice")
    decided = Decision(label="invoice", source="model", evidence=(evidence,))

    assert decided.actionable
    assert not decided.model_copy(update={"refused": "evidence"}).actionable


def test_a_step_result_round_trips_as_json() -> None:
    step = StepResult(
        step="model",
        prompt_version="system.v1",
        model="local-small",
        result={"label": "invoice"},
        tokens_in=100,
        tokens_out=10,
        duration_ms=250,
        at=datetime(2026, 11, 17, tzinfo=UTC),
    )

    assert StepResult.model_validate_json(step.model_dump_json()) == step


def test_a_step_is_one_of_the_three() -> None:
    with pytest.raises(ValidationError):
        StepResult(step="other", at=datetime(2026, 11, 17, tzinfo=UTC))
