"""What a recognizer is and answers, apart from the recognizers, so a
recognizer in a module of its own can stand on it. See
docs/mailbox-agents/concept/sorting-chain.md.
"""

from __future__ import annotations

from abc import ABC, abstractmethod
from dataclasses import dataclass, field
from typing import ClassVar

from ...contract import Context
from ...records import MailMessage
from .dimensions import Dimension

__all__ = ["Choice", "Recognizer"]


@dataclass(frozen=True)
class Choice:
    """The answer of a recognizer for one dimension: a category or
    ``none``, what to record, and the quote when the model chose.

    ``settled`` is False for an answer that leaves the dimension to the
    next recognizer, such as a sender two categories name alike.
    ``confidence`` is left None for now: a threshold would need a gold set
    large enough to measure it."""

    category: str
    details: dict[str, str] = field(default_factory=dict)
    quote: str | None = None
    by_model: bool = False
    settled: bool = True
    confidence: float | None = None


class Recognizer(ABC):
    """One way to find a category: its name, the version of what it asks
    or reads, and whether it asks the model for a dimension."""

    name: ClassVar[str]
    version: ClassVar[str]

    @abstractmethod
    def asks_model(self, dimension: Dimension) -> bool:
        """Whether it asks the model for ``dimension``."""

    def applies(self, dimension: Dimension) -> bool:
        """Whether ``dimension`` has a category for it. By default one that
        names it in ``recognize``."""
        return any(c.recognize == self.name for c in dimension.categories)

    def baseline(self, dimension: Dimension, message: MailMessage) -> Choice | None:
        """The answer by rules alone, None when it has none."""
        return None

    async def decide(
        self, dimension: Dimension, message: MailMessage, context: Context
    ) -> Choice | None:
        """The answer, with the model where it asks one. By default the
        answer by rules."""
        return self.baseline(dimension, message)
