"""What a peer is told of one message it asked an agent to classify:
the categories and whether each was backed by a quote, never the quote
or anything else of the mail. See docs/mailbox-agents/concept/a2a.md."""

from __future__ import annotations

from typing import Literal

from pydantic import BaseModel, ConfigDict, Field

__all__ = ["Classified", "NotClassified", "NotClassifiedReason"]

# Why a message was not classified, as a peer is told.
NotClassifiedReason = Literal[
    "message_gone",
    "message_refused",
    "limit_reached",
    "answer_refused",
    "unavailable",
]


class Classified(BaseModel):
    """The decision of an agent on one message, for a peer.

    ``label`` and ``fields`` are the decision's own. ``found`` says per
    field, the label under ``label``, whether its quote was found in the
    mail or code chose it. ``version`` is the agent's prompt version.
    """

    model_config = ConfigDict(frozen=True, extra="forbid")

    agent: str
    version: str
    label: str
    source: Literal["baseline", "model"]
    fields: dict[str, str] = Field(default_factory=dict)
    found: dict[str, bool] = Field(default_factory=dict)
    refused: str | None = None


class NotClassified(BaseModel):
    """A message the agent could not classify, and why."""

    model_config = ConfigDict(frozen=True, extra="forbid")

    agent: str
    reason: NotClassifiedReason
