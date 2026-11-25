"""How a dimension finds the category of a message: the recognizers.

A recognizer reads a message and answers a category of a dimension, or
``none``, with the details to record and, when the model chose, the quote
that shows it. It changes nothing. Those that ask no model run first, in
the order of :data:`RECOGNIZERS`: the first that settles the dimension
decides. Those that ask the model run only when none of them settled it,
and only in ``decide``. ``sender`` reads the sender rules, ``keyword`` the
keywords a message carries, ``topic`` asks the model among the categories
with a topic, ``invoice`` whether a message is an invoice. Another recognizer is a
subclass of :class:`Recognizer` and an entry in :data:`RECOGNIZERS`, named
by a category's ``recognize`` (decided 2026-11-25). See
docs/mailbox-agents/concept/agent-categorization.md.
"""

from __future__ import annotations

from functools import cached_property

from ...contract import Context, load_prompt
from ...records import MailMessage
from .choice import Choice, Recognizer
from .dimensions import Dimension
from .groups import NONE
from .invoice import Invoice
from .schema import answer_for, parts, render, system_for

__all__ = [
    "PROMPT",
    "RECOGNIZERS",
    "Choice",
    "Invoice",
    "Keywords",
    "Recognizer",
    "Sender",
    "Topic",
]

# The version of the fixed text of the prompt of ``topic``.
PROMPT = "v1"


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


class Keywords(Recognizer):
    """The keywords a message carries: the category whose keywords it all
    carries settles it, by code, without a quote. Of several the one that
    names most wins, two alike leave it to none. A keyword set by an
    earlier instance or by a person is read so (decided 2026-11-25)."""

    name = "keyword"
    version = "1"

    def asks_model(self, dimension: Dimension) -> bool:
        return False

    def applies(self, dimension: Dimension) -> bool:
        return any(c.keywords for c in dimension.categories)

    def baseline(self, dimension: Dimension, message: MailMessage) -> Choice | None:
        found = [
            category
            for category in dimension.categories
            if category.keywords
            and all(message.has_keyword(k) for k in category.keywords)
        ]
        if not found:
            return None
        most = max(len(c.keywords) for c in found)
        top = [c for c in found if len(c.keywords) == most]
        if len(top) > 1:
            return Choice(
                NONE,
                {"match": "ambiguous", "groups": ",".join(c.name for c in top)},
                settled=False,
            )
        details = {"match": "keyword"}
        if top[0].hold:
            details["hold"] = "yes"
        return Choice(top[0].name, details)


# The recognizers a list may use, by name, in the order they run.
RECOGNIZERS: dict[str, Recognizer] = {
    recognizer.name: recognizer
    for recognizer in (Sender(), Keywords(), Topic(), Invoice())
}
