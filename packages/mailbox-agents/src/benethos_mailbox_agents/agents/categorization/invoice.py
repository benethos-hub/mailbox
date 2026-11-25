"""The recognizer ``invoice``: is a message an invoice?

The model answers ``invoice`` or ``other``, for one that is not which near
miss it is, with a quote, in the prompt ``invoice.v5``, a copy of the
prompt ``v5`` of the agent ``invoices``, as are its schema and its rules.
A category that names ``"recognize": "invoice"`` holds for an invoice.
The near miss is recorded in the details. Its version, ``v5``, is part of
the version of every list that uses it (decided 2026-11-25). See
docs/mailbox-agents/concept/categorization-chain.md.
"""

from __future__ import annotations

from functools import cached_property
from typing import Literal

from pydantic import BaseModel, ConfigDict

from ...contract import Context, load_prompt
from ...records import MailMessage
from .choice import Choice, Recognizer
from .dimensions import Category, Dimension
from .groups import NONE
from .invoice_rules import baseline as rules
from .schema import parts, render

__all__ = ["Answer", "Invoice"]

# The version of the prompt, a copy of the one of the agent invoices.
PROMPT = "v5"


class Answer(BaseModel):
    """The answer of the model."""

    model_config = ConfigDict(extra="forbid")

    label: Literal["invoice", "other"]
    near_miss: Literal[
        "reminder", "quotation", "order_confirmation", "payment_receipt", "none"
    ]
    quote: str


def _category(dimension: Dimension) -> Category | None:
    """The category of ``dimension`` that names this recognizer."""
    return next((c for c in dimension.categories if c.recognize == "invoice"), None)


class Invoice(Recognizer):
    """Whether a message is an invoice, by the model, once."""

    name = "invoice"
    version = PROMPT

    @cached_property
    def system(self) -> str:
        return load_prompt(__package__ or "", "invoice", PROMPT)

    def asks_model(self, dimension: Dimension) -> bool:
        return self.applies(dimension)

    def rules(self, dimension: Dimension, message: MailMessage) -> Choice | None:
        """The answer of its rules alone, which the evaluation sets beside
        the model. Not asked in operation: the model decides."""
        category = _category(dimension)
        if category is None:
            return None
        found = rules(message)
        details = {"match": "invoice_rules"}
        if "near_miss" in found.fields:
            details["near_miss"] = found.fields["near_miss"]
        name = category.name if found.label == "invoice" else NONE
        return Choice(name, details)

    async def decide(
        self, dimension: Dimension, message: MailMessage, context: Context
    ) -> Choice | None:
        category = _category(dimension)
        if category is None:
            return None
        answer = await context.model.ask(
            system=self.system,
            content=render(message),
            evidence=parts(message),
            schema=Answer,
        )
        details = {"match": "invoice", "among": "invoice"}
        if answer.near_miss != "none":
            details["near_miss"] = answer.near_miss
        if answer.label != "invoice":
            # none needs no quote in the chain: nothing is done on it. The
            # quote goes along for the recognizer scored alone.
            return Choice(
                NONE, {**details, "match": "none"}, quote=answer.quote, by_model=True
            )
        if category.hold:
            details["hold"] = "yes"
        return Choice(category.name, details, quote=answer.quote, by_model=True)
