"""The chain of ``categorization``: dimensions, each with its categories, and
what follows from a category.

A list names one or more dimensions, such as the partner of a mail and
its kind. A dimension sorts a message into one of its categories, by the
sender rules, by a topic the model reads, or by a recognizer of
:data:`~.recognizers.RECOGNIZERS` the category names. ``when`` lets a
dimension run only after given categories of an earlier one. A category
names in ``then`` what is done with its mail, each entry an action of
:data:`~.actions.ACTIONS`. ``on`` says which mail the list takes up
(decided 2026-11-25). A list of the older form, ``groups`` alone, is read
as one dimension called ``group``, see :mod:`.lists`. See
docs/mailbox-agents/concept/agent-categorization.md.
"""

from __future__ import annotations

import re
from typing import Any, Literal

from pydantic import (
    BaseModel,
    ConfigDict,
    Field,
    StrictBool,
    StrictInt,
    field_validator,
    model_validator,
)

from ...contract import KEYWORD_FORM, from_top, is_pattern, waits_for
from .actions import ACTIONS, Keyword, Move, MoveBelow, Stage
from .groups import (
    NONE,
    Entry,
    Match,
    candidates_in,
    check_rules,
    match_in,
)

__all__ = [
    "MAX_DIMENSIONS",
    "Category",
    "Chain",
    "Dimension",
    "On",
    "Step",
]

# At most this many dimensions: each may ask the model, and the list stays
# one a person can read.
MAX_DIMENSIONS = 4

_DIMENSION = re.compile(r"^[a-z][a-z0-9_]*$")


class Step(BaseModel):
    """One entry of ``then``: an action, its value as the action read it,
    and the stage it runs in at most."""

    model_config = ConfigDict(frozen=True, extra="forbid")

    action: str
    params: dict[str, Any]
    stage: Stage | None = None

    @model_validator(mode="before")
    @classmethod
    def _read(cls, value: Any) -> Any:
        """``{"move": "Providers/Bank", "stage": "suggest"}``: one action by
        its name, its value, and a stage."""
        if not isinstance(value, dict) or "action" in value:
            return value
        named = [key for key in value if key != "stage"]
        if len(named) != 1:
            raise ValueError("an entry of then names one action")
        name = named[0]
        action = ACTIONS.get(name)
        if action is None:
            raise ValueError(
                f"an entry of then names no action of {', '.join(sorted(ACTIONS))}"
            )
        found: dict[str, Any] = {
            "action": name,
            "params": action.parse(value[name]),
        }
        if "stage" in value:
            found["stage"] = value["stage"]
        return found


class Category(Entry):
    """One category of a dimension: the sender rules, the topic and the
    recognizer that find it, how it ranks among the moves of the chain, and
    what follows from it."""

    recognize: str | None = Field(default=None, pattern=r"^[a-z][a-z0-9_]*$")
    # The keywords a message carries, all of them, for the recognizer
    # keyword: set by an earlier instance or by a person.
    keywords: tuple[str, ...] = ()
    priority: StrictInt = 0
    then: tuple[Step, ...] = ()

    @model_validator(mode="after")
    def _what_it_names(self) -> Category:
        if (
            not self.senders
            and self.topic is None
            and self.recognize is None
            and not self.keywords
        ):
            raise ValueError(
                f"category {self.name!r}: a category names senders, a topic, "
                "keywords or a recognizer"
            )
        for keyword in self.keywords:
            if not KEYWORD_FORM.fullmatch(keyword):
                raise ValueError(
                    f"category {self.name!r}: a keyword is lower case letters, "
                    "digits and dashes"
                )
        if self.recognize is None:
            self._check_topic()
        moves = [step for step in self.then if step.action == Move.name]
        belows = [step for step in self.then if step.action == MoveBelow.name]
        if len(moves) > 1 or len(belows) > 1:
            raise ValueError(
                f"category {self.name!r}: then names one move and one move_below "
                "at most"
            )
        return self

    def steps(self, action: str) -> tuple[Step, ...]:
        """The entries of ``then`` of the action called ``action``."""
        return tuple(step for step in self.then if step.action == action)

    @property
    def target(self) -> str | None:
        """The folder of its move, or None."""
        found = self.steps(Move.name)
        return str(found[0].params["target"]) if found else None

    @property
    def below(self) -> str | None:
        """The folder of its move_below, or None."""
        found = self.steps(MoveBelow.name)
        return str(found[0].params["target"]) if found else None


class Dimension(BaseModel):
    """One dimension: its name, its categories, and the categories of
    earlier dimensions it runs after."""

    model_config = ConfigDict(frozen=True, extra="forbid")

    name: str = Field(min_length=1, max_length=40)
    categories: tuple[Category, ...] = Field(min_length=1)
    when: dict[str, tuple[str, ...]] = Field(default_factory=dict)

    @field_validator("name")
    @classmethod
    def _name(cls, value: str) -> str:
        if not _DIMENSION.match(value):
            raise ValueError(
                "a dimension is named in lower case letters, digits and _, a "
                "letter first"
            )
        return value

    @field_validator("categories")
    @classmethod
    def _unique(cls, value: tuple[Category, ...]) -> tuple[Category, ...]:
        seen: set[str] = set()
        for category in value:
            key = category.name.casefold()
            if key in seen:
                raise ValueError(f"two categories share the name {key!r}")
            seen.add(key)
        check_rules(value)
        return value

    def match(self, address: str | None) -> Match[Category] | None:
        """The categories ``address`` belongs to by their sender rules."""
        return match_in(self.categories, address)

    def candidates(self, address: str | None) -> tuple[Category, ...]:
        """The categories a model chooses among by their topics."""
        return candidates_in(self.categories, address)

    @property
    def topical(self) -> tuple[Category, ...]:
        return tuple(c for c in self.categories if c.topic is not None)

    def named(self, name: str) -> Category | None:
        """The category called ``name``, or None."""
        return next((c for c in self.categories if c.name == name), None)


class On(BaseModel):
    """Which mail the list takes up: mail that arrives in the inbox, or in
    a folder without a role as well, and mail that is given a keyword, by
    an earlier instance or by a person (decided 2026-11-25). A pattern
    ends in ``*`` for every keyword it starts. Without ``arrival`` beside
    ``keywords`` the list waits for a keyword alone."""

    model_config = ConfigDict(frozen=True, extra="forbid")

    arrival: Literal["inbox", "folders"] | None = "inbox"
    keywords: tuple[str, ...] = ()

    @model_validator(mode="before")
    @classmethod
    def _keywords_alone(cls, value: Any) -> Any:
        if isinstance(value, dict) and "keywords" in value and "arrival" not in value:
            return {**value, "arrival": None}
        return value

    @field_validator("keywords")
    @classmethod
    def _patterns(cls, value: tuple[str, ...]) -> tuple[str, ...]:
        for pattern in value:
            if not is_pattern(pattern):
                raise ValueError(
                    "a keyword of on is lower case letters, digits and dashes, "
                    "a * at its end for every keyword it starts"
                )
        return value

    @model_validator(mode="after")
    def _something(self) -> On:
        if self.arrival is None and not self.keywords:
            raise ValueError("on names an arrival, keywords or both")
        return self

    def waits_for(self, keyword: str) -> bool:
        """Whether ``keyword`` is one the list waits for, case aside."""
        return waits_for(self.keywords, keyword)


class Chain(BaseModel):
    """The whole list: which mail it takes up, and its dimensions in the
    order they run."""

    model_config = ConfigDict(frozen=True, extra="forbid")

    on: On = Field(default_factory=On)
    # The agent's keyword after every decision, none included, not only
    # with a move: a sign for a later instance that this one is done.
    mark_done: StrictBool = False
    dimensions: tuple[Dimension, ...] = Field(min_length=1)

    @model_validator(mode="after")
    def _no_loop(self) -> Chain:
        """A list never waits for a keyword it sets itself (decided
        2026-11-25): it would set itself off again."""
        for keyword in self.keywords():
            if self.on.waits_for(keyword):
                raise ValueError(
                    "on.keywords names a keyword the list sets in then: it "
                    "would set itself off"
                )
        return self

    @field_validator("dimensions")
    @classmethod
    def _order(cls, value: tuple[Dimension, ...]) -> tuple[Dimension, ...]:
        if len(value) > MAX_DIMENSIONS:
            raise ValueError(f"a list has at most {MAX_DIMENSIONS} dimensions")
        earlier: dict[str, Dimension] = {}
        for dimension in value:
            if dimension.name in earlier:
                raise ValueError(f"two dimensions share the name {dimension.name!r}")
            for name, categories in dimension.when.items():
                before = earlier.get(name)
                if before is None:
                    raise ValueError(
                        f"dimension {dimension.name!r}: when names no earlier dimension"
                    )
                for category in categories:
                    if category != NONE and before.named(category) is None:
                        raise ValueError(
                            f"dimension {dimension.name!r}: when names a "
                            f"category {name!r} does not have"
                        )
            earlier[dimension.name] = dimension
        _spelt_alike(value)
        return value

    @property
    def first(self) -> Dimension:
        return self.dimensions[0]

    def folders(self) -> frozenset[str]:
        """Every folder a move of the list may go to, with the folders above
        it: each move target, and each with a move_below of the list below."""
        targets = {c.target for d in self.dimensions for c in d.categories}
        belows = {c.below for d in self.dimensions for c in d.categories}
        found: set[str] = set()
        for target in targets - {None}:
            found.update(from_top(target or ""))
            for below in belows - {None}:
                found.update(from_top(f"{target}/{below}"))
        return frozenset(found)

    def keywords(self) -> frozenset[str]:
        """Every keyword an entry of ``then`` sets."""
        return frozenset(
            str(step.params["target"])
            for dimension in self.dimensions
            for category in dimension.categories
            for step in category.steps(Keyword.name)
        )

    def belows(self) -> frozenset[str]:
        """Every folder below another that a move_below of the list names,
        with those above it, relative to the folder it is made in."""
        found: set[str] = set()
        for dimension in self.dimensions:
            for category in dimension.categories:
                if category.below is not None:
                    found.update(from_top(category.below))
        return frozenset(found)


def _spelt_alike(dimensions: tuple[Dimension, ...]) -> None:
    """Raise a ValueError when two categories write a folder of a move,
    theirs or one above it, in another case: the executor refuses a folder
    whose name exists in another case. The message names the categories,
    not the folder."""
    spelt: dict[str, tuple[str, str]] = {}
    for dimension in dimensions:
        for category in dimension.categories:
            for path in from_top(category.target or "") if category.target else ():
                first = spelt.setdefault(path.casefold(), (path, category.name))
                if first[0] != path:
                    raise ValueError(
                        f"category {category.name!r}: a folder differs from one "
                        f"of category {first[1]!r} in case only"
                    )
