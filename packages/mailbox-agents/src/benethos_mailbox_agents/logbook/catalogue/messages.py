"""The steps of one message. A message is named by its id, never by its
subject or its sender."""

from __future__ import annotations

import logging
from dataclasses import dataclass
from typing import ClassVar

from ..activity import Activity, Failure


@dataclass(frozen=True, slots=True, kw_only=True)
class StateSet(Activity):
    name: ClassVar[str] = "state_set"

    message_id: str
    state: str

    def says(self) -> str:
        return f"set message {self.message_id} to {self.state}"


@dataclass(frozen=True, slots=True, kw_only=True)
class StepDone(Activity):
    name: ClassVar[str] = "step_done"
    level: ClassVar[int] = logging.DEBUG

    message_id: str
    step: str
    ms: int

    def says(self) -> str:
        return f"finished step {self.step} of message {self.message_id} in {self.ms}ms"


@dataclass(frozen=True, slots=True, kw_only=True)
class StepFailed(Failure):
    name: ClassVar[str] = "step_failed"

    message_id: str
    step: str

    def says(self) -> str:
        return f"failed step {self.step} of message {self.message_id}"


@dataclass(frozen=True, slots=True, kw_only=True)
class AnswerRefused(Activity):
    """The model's answer failed the schema, or the gateway refused the
    request. ``reason`` is ``schema`` or ``request``."""

    name: ClassVar[str] = "answer_refused"
    level: ClassVar[int] = logging.WARNING

    message_id: str
    reason: str

    def says(self) -> str:
        return f"refused the model's answer on message {self.message_id}"

    def why(self) -> str | None:
        return self.reason


@dataclass(frozen=True, slots=True, kw_only=True)
class QuoteMissing(Activity):
    """The model gave a quote for ``field`` that is not in the mail."""

    name: ClassVar[str] = "quote_missing"

    message_id: str
    field: str

    def says(self) -> str:
        return f"found no quote for {self.field} in message {self.message_id}"
