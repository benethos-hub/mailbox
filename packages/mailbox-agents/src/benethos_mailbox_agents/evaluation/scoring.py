"""The scoring: where an agent agrees with the gold set, as numbers.

For the label, precision and recall per label. For each field, how often
the value is right, wrong, missing or invented, and how often the field is
rightly empty. Values are compared with case and whitespace made uniform.
A decision the evidence check refused counts as no answer, since the agent
does not act on it. The rules alone are scored the same way, beside the
model. See docs/mailbox-agents/concept/evaluation.md.
"""

from __future__ import annotations

from collections.abc import Iterable
from dataclasses import dataclass, field

from ..records import Decision
from .gold import GoldItem

__all__ = [
    "FieldScore",
    "LabelScore",
    "Outcome",
    "Scores",
    "same_label",
    "score",
]


def _uniform(value: str | None) -> str:
    return " ".join((value or "").split()).casefold()


def same_label(expected: str | None, found: str | None) -> bool:
    return _uniform(expected) == _uniform(found)


@dataclass
class LabelScore:
    label: str
    true_positive: int = 0
    false_positive: int = 0
    false_negative: int = 0

    @property
    def precision(self) -> float | None:
        said = self.true_positive + self.false_positive
        return self.true_positive / said if said else None

    @property
    def recall(self) -> float | None:
        there = self.true_positive + self.false_negative
        return self.true_positive / there if there else None


@dataclass
class FieldScore:
    field: str
    right: int = 0
    wrong: int = 0
    missing: int = 0
    invented: int = 0
    empty: int = 0

    def count(self, expected: str | None, found: str | None) -> None:
        if not _uniform(expected) and not _uniform(found):
            self.empty += 1
        elif not _uniform(found):
            self.missing += 1
        elif not _uniform(expected):
            self.invented += 1
        elif same_label(expected, found):
            self.right += 1
        else:
            self.wrong += 1


@dataclass
class Outcome:
    """One gold message run through the agent: what the model path and the
    rules decided, and what it cost. ``decision`` is None when no answer
    came, with ``failure`` naming why."""

    item: GoldItem
    baseline: Decision | None
    decision: Decision | None
    tokens_in: int = 0
    tokens_out: int = 0
    duration_ms: int = 0
    failure: str | None = None
    models: tuple[str, ...] = ()


@dataclass
class Scores:
    """The scores of one side, the model or the rules."""

    messages: int = 0
    agreed: int = 0
    unanswered: int = 0
    refused: int = 0
    labels: dict[str, LabelScore] = field(default_factory=dict)
    fields: dict[str, FieldScore] = field(default_factory=dict)

    @property
    def accuracy(self) -> float | None:
        return self.agreed / self.messages if self.messages else None

    def _label(self, name: str) -> LabelScore:
        return self.labels.setdefault(name, LabelScore(name))

    def _field(self, name: str) -> FieldScore:
        return self.fields.setdefault(name, FieldScore(name))

    def add(self, item: GoldItem, decision: Decision | None) -> None:
        self.messages += 1
        if decision is not None and not decision.actionable:
            self.refused += 1
        found = decision.label if decision is not None and decision.actionable else None
        if found is None:
            self.unanswered += 1
        self._label(item.label)
        if found is not None:
            self._label(found)
        if found == item.label:
            self.agreed += 1
            self._label(item.label).true_positive += 1
        else:
            self._label(item.label).false_negative += 1
            if found is not None:
                self._label(found).false_positive += 1
        values = decision.fields if decision is not None and decision.actionable else {}
        for name, expected in item.fields.items():
            self._field(name).count(expected, values.get(name))


def score(outcomes: Iterable[Outcome]) -> tuple[Scores, Scores]:
    """The scores of the model and of the rules, over the same messages."""
    model, rules = Scores(), Scores()
    for outcome in outcomes:
        model.add(outcome.item, outcome.decision)
        rules.add(outcome.item, outcome.baseline)
    return model, rules
