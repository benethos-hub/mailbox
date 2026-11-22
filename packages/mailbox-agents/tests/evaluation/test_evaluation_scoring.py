"""The scoring per label and per field, the rules beside the model."""

from __future__ import annotations

import pytest

from benethos_mailbox_agents.evaluation.gold import GoldItem
from benethos_mailbox_agents.evaluation.scoring import (
    FieldScore,
    LabelScore,
    Outcome,
    same,
    score,
)
from benethos_mailbox_agents.records import Decision


def gold(label: str, **fields: str | None) -> GoldItem:
    return GoldItem(account_id="a", message_id=label, label=label, fields=fields)


def decided(label: str, source: str = "model", **fields: str) -> Decision:
    return Decision(label=label, source=source, fields=fields)


def test_same_ignores_case_and_whitespace() -> None:
    assert same("Cloud  Host", "cloud host")
    assert not same("CloudHost", "Telco")
    assert same(None, "  ")


def test_precision_and_recall_per_label() -> None:
    outcomes = [
        Outcome(gold("invoice"), None, decided("invoice")),
        Outcome(gold("invoice"), None, decided("other")),
        Outcome(gold("other"), None, decided("invoice")),
        Outcome(gold("other"), None, decided("other")),
        Outcome(gold("other"), None, decided("other")),
    ]

    model, _ = score(outcomes)

    invoice = model.labels["invoice"]
    assert (invoice.true_positive, invoice.false_positive, invoice.false_negative) == (
        1,
        1,
        1,
    )
    assert invoice.precision == 0.5
    assert invoice.recall == 0.5
    assert model.labels["other"].precision == pytest.approx(2 / 3)
    assert model.accuracy == pytest.approx(3 / 5)


def test_no_answer_and_a_refusal_count_as_unanswered() -> None:
    refused = decided("invoice").model_copy(update={"refused": "evidence"})
    outcomes = [
        Outcome(gold("invoice"), None, None, failure="answer_refused"),
        Outcome(gold("invoice"), None, refused),
    ]

    model, _ = score(outcomes)

    assert (model.unanswered, model.refused, model.agreed) == (2, 1, 0)
    assert model.labels["invoice"].false_negative == 2
    assert model.labels["invoice"].precision is None


def test_each_field_right_wrong_missing_invented_or_empty() -> None:
    field = FieldScore("supplier")
    for expected, found in [
        ("CloudHost", "cloudhost"),
        ("CloudHost", "Telco"),
        ("CloudHost", None),
        (None, "Telco"),
        (None, None),
    ]:
        field.count(expected, found)

    assert (field.right, field.wrong, field.missing, field.invented, field.empty) == (
        1,
        1,
        1,
        1,
        1,
    )


def test_the_rules_are_scored_beside_the_model() -> None:
    outcomes = [
        Outcome(gold("invoice"), decided("other", "baseline"), decided("invoice")),
        Outcome(gold("other"), decided("other", "baseline"), decided("other")),
    ]

    model, rules = score(outcomes)

    assert (model.agreed, rules.agreed) == (2, 1)
    assert rules.labels["invoice"].recall == 0.0


def test_an_empty_score_has_no_ratios() -> None:
    assert LabelScore("x").precision is None
    assert LabelScore("x").recall is None
    model, _ = score([])
    assert model.accuracy is None
