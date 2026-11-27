"""The loop of the worker: its passes, its ticks, an upstream away."""

from __future__ import annotations

import logging
from dataclasses import dataclass
from typing import ClassVar

from benethos_mailbox_common.values import text as text_values

from ..activity import Activity, Failure


@dataclass(frozen=True, slots=True, kw_only=True)
class PassDone(Activity):
    name: ClassVar[str] = "pass_done"
    level: ClassVar[int] = logging.DEBUG

    seconds: float
    pending: int

    def says(self) -> str:
        return (
            f"finished a pass in {self.seconds:.2f}s with "
            f"{text_values.plural(self.pending, 'message')} pending"
        )


@dataclass(frozen=True, slots=True, kw_only=True)
class PassFailed(Failure):
    """A pass failed with an error of the agent's own. The loop waits
    ``wait`` seconds and tries again, as after an upstream away."""

    name: ClassVar[str] = "pass_failed"
    level: ClassVar[int] = logging.ERROR

    wait: float

    def says(self) -> str:
        return f"failed a pass and waits {self.wait:.0f}s"


@dataclass(frozen=True, slots=True, kw_only=True)
class UpstreamAway(Failure):
    """The mailbox service, the gateway or the database of the state did
    not answer. The loop waits ``wait`` seconds and tries again."""

    name: ClassVar[str] = "upstream_away"

    wait: float

    def says(self) -> str:
        return f"found an upstream away and waits {self.wait:.0f}s"


@dataclass(frozen=True, slots=True, kw_only=True)
class TickDone(Activity):
    name: ClassVar[str] = "tick_done"

    actions: int

    def says(self) -> str:
        return f"ticked with {text_values.plural(self.actions, 'action')}"
