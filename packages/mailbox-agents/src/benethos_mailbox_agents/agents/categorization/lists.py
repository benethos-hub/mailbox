"""Reading the list of ``categorization``, in either of its two forms.

A list of ``dimensions`` is read as a :class:`~.dimensions.Chain`. A list
of ``groups`` alone, the form before the chain, is read as one dimension
called ``group``: each group a category whose ``then`` moves to its
folder. Such a list keeps the version it had, so nothing it decided is
taken up again (decided 2026-11-25). The version of a list is a digest of
it as read, beside the versions of the recognizers it uses besides
``sender`` and ``topic``. See docs/mailbox-agents/concept/agent-categorization.md.
"""

from __future__ import annotations

import json
from collections.abc import Mapping
from dataclasses import dataclass
from pathlib import Path
from typing import Any

from benethos_mailbox_common.values import secret

from ...errors import ConfigError, describe_invalid
from .dimensions import Category, Chain, Dimension
from .groups import READERS, Groups
from .recognizers import RECOGNIZERS, Recognizer

__all__ = [
    "GROUP",
    "MAX_MODEL",
    "ListRefusedError",
    "Listed",
    "circles",
    "list_digest",
    "load_chain",
    "read_chain",
    "used",
]

# The name of the one dimension of a list of groups.
GROUP = "group"

# At most this many recognizers of a list ask the model: each is one call
# per message.
MAX_MODEL = 2

# The recognizers whose version the version of the prompt holds already.
_IN_PROMPT = frozenset({"sender", "topic", "keyword"})


class ListRefusedError(ValueError):
    """A list refused by a check of its own, its message safe to show: it
    names a category or a dimension, never a rule or a topic."""


@dataclass(frozen=True)
class Listed:
    """A list as read: the chain, and its version."""

    chain: Chain
    version: str


def list_digest(groups: Groups) -> str:
    """The version of a list of groups: a digest of the groups as read, in
    JSON with sorted keys, so the same list gives the same version. A group
    without a topic is read without ``topic`` and ``by_topic``, so a list
    written before either existed keeps its version."""
    found = []
    for group in groups.groups:
        read = group.model_dump(mode="json")
        if group.topic is None:
            del read["topic"], read["by_topic"]
        found.append(read)
    normal = json.dumps({"groups": found}, sort_keys=True)
    return "list-" + secret.digest(normal)[:12]


def _from_groups(groups: Groups) -> Chain:
    """A list of groups as a chain of one dimension."""
    categories = tuple(
        Category.model_validate(
            {
                **group.model_dump(exclude={"folder"}, exclude_unset=True),
                "then": [{"move": group.folder}],
            }
        )
        for group in groups.groups
    )
    return Chain(dimensions=(Dimension(name=GROUP, categories=categories),))


def used(chain: Chain) -> list[Recognizer]:
    """The recognizers the list uses, in the order they run."""
    return [
        recognizer
        for recognizer in RECOGNIZERS.values()
        if any(recognizer.applies(d) for d in chain.dimensions)
    ]


def _check_names(chain: Chain) -> None:
    """Raise a ValueError for a recognizer the list names that does not
    exist, and for a list whose recognizers ask the model more than
    :data:`MAX_MODEL` times."""
    for dimension in chain.dimensions:
        for category in dimension.categories:
            if category.recognize and category.recognize not in RECOGNIZERS:
                raise ListRefusedError(
                    f"category {category.name!r}: recognize names no recognizer "
                    f"of {', '.join(sorted(RECOGNIZERS))}"
                )
    asking = sum(
        1
        for dimension in chain.dimensions
        for recognizer in RECOGNIZERS.values()
        if recognizer.applies(dimension) and recognizer.asks_model(dimension)
    )
    if asking > MAX_MODEL:
        raise ListRefusedError(
            f"at most {MAX_MODEL} recognizers of a list ask the model"
        )


def read_chain(data: Any) -> Listed:
    """The list in ``data``, read from its file, or a ValueError: a
    :class:`ListRefusedError` or a validation error."""
    if isinstance(data, dict) and "groups" in data:
        if "dimensions" in data:
            raise ListRefusedError("a list names groups or dimensions, not both")
        groups = Groups.model_validate(data)
        chain = _from_groups(groups)
        base = list_digest(groups)
    else:
        chain = Chain.model_validate(data)
        normal = json.dumps(chain.model_dump(mode="json"), sort_keys=True)
        base = "list-" + secret.digest(normal)[:12]
    _check_names(chain)
    extra = [r for r in used(chain) if r.name not in _IN_PROMPT]
    version = base + "".join(f"-{r.name}-{r.version}" for r in extra)
    return Listed(chain=chain, version=version)


def circles(chains: Mapping[str, Chain], sign: str) -> list[list[str]]:
    """The circles among the lists of several instances, each list by the
    name of its instance: one sets a keyword another waits for, and so on
    back to the first. ``sign`` is the agent's keyword, which an instance
    sets with ``-<instance>`` after it with a move or with ``mark_done``.
    Each circle once, from the instance first in ``chains``."""
    sets: dict[str, set[str]] = {}
    for name, chain in chains.items():
        found = set(chain.keywords())
        if chain.mark_done or chain.folders():
            found.add(f"{sign}-{name}")
        sets[name] = found
    after = {
        name: [
            other
            for other, chain in chains.items()
            if any(chain.on.waits_for(k) for k in sets[name])
        ]
        for name in chains
    }
    found_circles: list[list[str]] = []
    seen: set[frozenset[str]] = set()

    def walk(path: list[str]) -> None:
        for other in after[path[-1]]:
            if other == path[0]:
                key = frozenset(path)
                if key not in seen:
                    seen.add(key)
                    found_circles.append([*path, other])
            elif other not in path:
                walk([*path, other])

    for name in chains:
        walk([name])
    return found_circles


def load_chain(path: Path) -> Listed:
    """The list at ``path``, or a :class:`ConfigError` that says what is
    wrong with it."""
    reader = READERS.get(path.suffix.lower())
    if reader is None:
        raise ConfigError(
            f"the categorization list {path.name} is no "
            f"{', '.join(sorted(READERS))} file"
        )
    try:
        # utf-8-sig: an editor may start the file with the mark of UTF-8.
        text = path.read_text(encoding="utf-8-sig")
    except (OSError, ValueError) as exc:
        # A ValueError: a file in another encoding than UTF-8.
        raise ConfigError(
            f"the categorization list {path.name} cannot be read ({type(exc).__name__})"
        ) from None
    try:
        return read_chain(reader(text))
    except ListRefusedError as exc:
        raise ConfigError(f"the categorization list {path.name}: {exc}") from None
    except ValueError as exc:
        raise ConfigError(
            f"the categorization list {path.name}: {describe_invalid(exc)}"
        ) from None
