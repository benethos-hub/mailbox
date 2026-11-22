"""What an agent decides, and what a step leaves in the state file."""

from __future__ import annotations

from datetime import datetime
from typing import Any, Literal

from pydantic import BaseModel, ConfigDict, Field

__all__ = ["LABEL", "Decision", "Evidence", "Step", "StepResult"]

# The steps of a message, as the state file names them.
Step = Literal["baseline", "model", "decision"]

# The field name under which the evidence of the label itself is kept.
LABEL = "label"


class Evidence(BaseModel):
    """A quote from the mail that backs one value.

    ``found`` is set by the evidence check in code, never by the model:
    ``None`` before the check, then whether the quote is in the text the
    model was given. A value that code found by a rule, such as a field
    a sender rule chose, has no quote and is ``True`` from the start,
    so nothing of the mail is stored for it. See docs/mailbox-agents/concept/safety.md.
    """

    model_config = ConfigDict(frozen=True, extra="forbid")

    field: str
    value: str | None
    quote: str
    found: bool | None = None


class Decision(BaseModel):
    """The answer to an agent's question about one message.

    ``source`` says who answered: the rules alone (``baseline``) or the
    model with the check in code (``model``). ``details`` holds what the
    agent wants recorded besides label and fields, such as which rule chose
    a folder. ``refused`` names why the decision is recorded and not acted
    on, such as a label whose quote was not found.
    """

    model_config = ConfigDict(frozen=True, extra="forbid")

    label: str
    source: Literal["baseline", "model"]
    fields: dict[str, str] = Field(default_factory=dict)
    evidence: tuple[Evidence, ...] = ()
    details: dict[str, str] = Field(default_factory=dict)
    refused: str | None = None

    @property
    def actionable(self) -> bool:
        return self.refused is None


class StepResult(BaseModel):
    """One step of one message, as the state file keeps it."""

    model_config = ConfigDict(frozen=True, extra="forbid")

    step: Step
    prompt_version: str = ""
    model: str = ""
    result: dict[str, Any] = Field(default_factory=dict)
    tokens_in: int = 0
    tokens_out: int = 0
    duration_ms: int = 0
    at: datetime
