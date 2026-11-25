"""What ``report`` and a span say of ``sorting``: per dimension and
category what became of its messages, and the dimensions of a decision.

A category with a move counts its messages as moved, recorded, recorded
by topic, held or not moved, as before the chain. A move that lost to the
priority of another dimension's counts as displaced by priority. A
category without a move counts its keywords as set or recorded, one with
nothing in ``then`` as only sorted. A list of groups keeps its heading
``groups:``, a list of dimensions names each dimension. See
docs/mailbox-agents/concept/agent-sorting.md.
"""

from __future__ import annotations

from collections import Counter

from ...contract import Action, Shown, TracePart
from ...records import LABEL, Decision
from .actions import Keyword
from .dimensions import Category, Chain, Dimension
from .groups import NONE
from .lists import GROUP
from .plan import BY_CODE, DISPLACED, key

__all__ = ["FATES", "fates", "parts_of"]

# The fates in the order a line names them.
FATES = (
    "moved",
    "recorded",
    "recorded by topic",
    "held",
    "not moved",
    "displaced by priority",
    "keyword set",
    "keyword recorded",
    "only sorted",
)


def _fate(
    item: Shown, index: int, dimension: Dimension, category: Category | None
) -> str:
    """What became of a message of ``category``, None for one the list no
    longer names, counted as one with a move."""
    details = item.decision.details
    if dimension.name in details.get(DISPLACED, "").split(","):
        return "displaced by priority"
    if category is None or category.target is not None or category.below is not None:
        moves = [a.done for a in item.actions if a.action is Action.MOVE_TO_FOLDER]
        if not moves:
            return "not moved"
        if any(moves):
            return "moved"
        if details.get(key(index, dimension, "hold")) == "yes":
            return "held"
        if (
            details.get(key(index, dimension, "match")) == "topic"
            and details.get(key(index, dimension, "by_topic")) == "record"
        ):
            return "recorded by topic"
        return "recorded"
    if category.steps(Keyword.name):
        added = [a.done for a in item.actions if a.action is Action.ADD_KEYWORD]
        return "keyword set" if any(added) else "keyword recorded"
    return "only sorted"


def _category(decision: Decision, index: int, dimension: Dimension) -> str | None:
    if index == 0:
        return decision.label
    return decision.fields.get(dimension.name)


def fates(chain: Chain, shown: list[Shown]) -> list[str]:
    """Per dimension and category what became of its messages, the
    categories in the order of their names."""
    lines: list[str] = []
    for index, dimension in enumerate(chain.dimensions):
        counted: dict[str, Counter[str]] = {}
        for item in shown:
            name = _category(item.decision, index, dimension)
            if name is None or name == NONE:
                continue
            fate = _fate(item, index, dimension, dimension.named(name))
            counted.setdefault(name, Counter())[fate] += 1
        if not counted:
            continue
        lines.append("groups:" if dimension.name == GROUP else f"{dimension.name}:")
        for name in sorted(counted):
            said = ", ".join(
                f"{counted[name][fate]} {fate}" for fate in FATES if counted[name][fate]
            )
            lines.append(f"  {name}: {said}")
    return lines


def _label(dimension: Dimension, name: str) -> str:
    """A category by its place in the dimension, ``label-<n>`` from 1,
    ``none`` for none, as an evaluation report names it."""
    if name == NONE:
        return NONE
    for number, category in enumerate(dimension.categories, start=1):
        if category.name == name:
            return f"label-{number}"
    return "label-0"


def parts_of(chain: Chain, decision: Decision) -> list[TracePart]:
    """A part for each dimension of ``decision`` that ran."""
    found: list[TracePart] = []
    quotes = {item.field: item.found for item in decision.evidence}
    for index, dimension in enumerate(chain.dimensions):
        name = _category(decision, index, dimension)
        if name is None:
            continue
        match = decision.details.get(key(index, dimension, "match"), "")
        field = LABEL if index == 0 else dimension.name
        attributes: dict[str, str | bool | int] = {
            "dimension": dimension.name,
            "recognizer": match,
            "source": "code" if match in BY_CODE else "model",
            "category": _label(dimension, name),
        }
        if quotes.get(field) is not None:
            attributes["quote_found"] = bool(quotes[field])
        found.append(TracePart("dimension", attributes))
    return found
