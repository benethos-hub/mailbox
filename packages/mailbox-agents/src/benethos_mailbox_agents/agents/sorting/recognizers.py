"""How a dimension finds the category of a message: the recognizers.

A recognizer reads a message and answers a category of a dimension, or
``none``, with the details to record and, when the model chose, the quote
that shows it. It changes nothing. Those that ask no model run first, in
the order of :data:`RECOGNIZERS`: the first that settles the dimension
decides. Those that ask the model run only when none of them settled it,
and only in ``decide``. ``sender`` reads the sender rules, ``topic`` asks
the model among the categories with a topic. Another recognizer is a
subclass of :class:`Recognizer` and an entry in :data:`RECOGNIZERS`, named
by a category's ``recognize`` (decided 2026-11-25). See
docs/mailbox-agents/concept/agent-sorting.md.
"""

from __future__ import annotations

from abc import ABC, abstractmethod
from dataclasses import dataclass, field
from functools import cached_property
from typing import ClassVar

from ...contract import Context, load_prompt
from ...records import MailMessage
from .dimensions import Dimension
from .groups import NONE
from .schema import answer_for, parts, render, system_for

__all__ = ["PROMPT", "RECOGNIZERS", "Choice", "Recognizer", "Sender", "Topic"]

# The version of the fixed text of the prompt of ``topic``.
PROMPT = "v1"


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


class Sender(Recognizer):
    """The sender rules: the category whose most specific rule matches the
    sender settles it. Two that match alike leave it to the model, when
    each has a topic, and to none otherwise."""

    name = "sender"
    version = "1"

    def asks_model(self, dimension: Dimension) -> bool:
        return False

    def applies(self, dimension: Dimension) -> bool:
        return any(c.senders for c in dimension.categories)

    def baseline(self, dimension: Dimension, message: MailMessage) -> Choice | None:
        found = dimension.match(message.sender.email if message.sender else None)
        if found is None:
            return Choice(NONE, {"match": "none"}, settled=False)
        category = found.group
        if category is None:
            return Choice(
                NONE,
                {
                    "match": "ambiguous",
                    "groups": ",".join(c.name for c in found.groups),
                },
                settled=False,
            )
        details = {"match": "group", "rule": found.kind.name.lower()}
        if category.hold:
            details["hold"] = "yes"
        return Choice(category.name, details)


class Topic(Recognizer):
    """The model, once, among the categories with a topic the sender
    rules leave open, with a quote the code looks up in the mail."""

    name = "topic"
    version = PROMPT

    @cached_property
    def system(self) -> str:
        """The fixed text of the prompt, the categories to choose from
        follow."""
        return load_prompt(__package__ or "", "system", PROMPT)

    def asks_model(self, dimension: Dimension) -> bool:
        return bool(dimension.topical)

    def applies(self, dimension: Dimension) -> bool:
        return bool(dimension.topical)

    async def decide(
        self, dimension: Dimension, message: MailMessage, context: Context
    ) -> Choice | None:
        address = message.sender.email if message.sender else None
        choice = dimension.candidates(address)
        if not choice:
            return None
        among = "senders" if dimension.match(address) is not None else "all"
        answer = await context.model.ask(
            system=system_for(self.system, choice),
            content=render(message),
            evidence=parts(message),
            schema=answer_for([category.name for category in choice]),
        )
        said = answer.model_dump()
        category = dimension.named(said["group"])
        if category is None:
            # none needs no quote: nothing is done on it (2026-11-24).
            return Choice(NONE, {"match": "none", "among": among}, by_model=True)
        details = {"match": "topic", "among": among, "by_topic": category.by_topic}
        if category.hold:
            details["hold"] = "yes"
        return Choice(category.name, details, quote=said["quote"], by_model=True)


# The recognizers a list may use, by name, in the order they run.
RECOGNIZERS: dict[str, Recognizer] = {
    recognizer.name: recognizer for recognizer in (Sender(), Topic())
}
