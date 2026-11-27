"""One recognizer of ``categorization`` as an agent of its own, for ``eval``.

``eval --agent categorization --recognizer invoice`` scores the recognizer alone,
its rules beside the model, in its own space: ``invoice`` or ``other``
with the near miss as a field, as the agent ``invoices`` answers. So the
gold set of ``invoices`` serves unchanged, and its numbers stand beside
those of ``invoices`` (decided 2026-11-25). It changes nothing: it has no
action. See docs/mailbox-agents/concept/categorization-chain.md.
"""

from __future__ import annotations

from ...contract import (
    ActionRequest,
    Agent,
    Classifier,
    Context,
    Limits,
    Route,
    Trigger,
)
from ...errors import ConfigError
from ...records import LABEL, Decision, Evidence, MailMessage
from .choice import Choice
from .dimensions import Category, Dimension
from .groups import NONE
from .invoice import Invoice

__all__ = ["ALONE", "InvoiceAlone", "alone"]

# The space of the recognizer invoice: its label for an invoice.
INVOICE = "invoice"

_DIMENSION = Dimension(
    name="alone", categories=(Category(name=INVOICE, recognize=INVOICE),)
)


def _decision(choice: Choice | None, source: str) -> Decision:
    """The answer of the recognizer as ``invoices`` gives it."""
    if choice is None:
        return Decision(label="other", source="baseline")
    label = INVOICE if choice.category != NONE else "other"
    fields = {}
    near_miss = choice.details.get("near_miss")
    if label == "other" and near_miss:
        fields["near_miss"] = near_miss
    if source == "baseline":
        return Decision(label=label, source="baseline", fields=fields)
    quote = choice.quote or ""
    evidence = [Evidence(field=LABEL, value=label, quote=quote)]
    if fields:
        evidence.append(Evidence(field="near_miss", value=near_miss, quote=quote))
    return Decision(
        label=label, source="model", fields=fields, evidence=tuple(evidence)
    )


class InvoiceAlone(Classifier):
    """The recognizer invoice of categorization alone."""

    name = "categorization"
    version = "3"
    description = "The recognizer invoice of categorization alone, for eval."
    triggers = Trigger(routes={"message.created": Route.DECIDE})
    actions = frozenset()
    limits = Limits(model_calls_per_message=1)
    default_keyword = "agent-categorized"
    prompt_version = f"{Invoice.name}-{Invoice.version}"
    report_labels = frozenset({INVOICE, "other"})
    report_fields = frozenset({"near_miss"})

    recognizer = Invoice()

    def baseline(self, message: MailMessage) -> Decision:
        return _decision(self.recognizer.rules(_DIMENSION, message), "baseline")

    async def decide(self, message: MailMessage, context: Context) -> Decision:
        found = await self.recognizer.decide(_DIMENSION, message, context)
        return _decision(found, "model")

    async def effect(
        self, decision: Decision, message: MailMessage, context: Context
    ) -> list[ActionRequest]:
        return []


# The recognizers that can be scored alone, by name.
ALONE: dict[str, type[Agent]] = {INVOICE: InvoiceAlone}


def alone(name: str, agent: Agent) -> Agent:
    """The recognizer called ``name`` of ``agent`` as an agent of its own,
    with the settings of ``agent``."""
    found = ALONE.get(name)
    if found is None:
        raise ConfigError(
            f"categorization scores alone the recognizers {', '.join(sorted(ALONE))}"
        )
    return found(agent.settings)
