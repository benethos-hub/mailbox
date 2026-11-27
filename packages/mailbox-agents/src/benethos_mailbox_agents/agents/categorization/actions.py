"""What follows from a category of the chain: the actions of ``then``.

A category names what is done with its mail, each entry one action of
:data:`ACTIONS` with its value, such as ``{"move": "Providers/Bank"}``. An
action reads no mail and asks no model. It sees the decision and
:class:`Placed`, where the message lies and which keywords it carries, and
answers the requests for the executor of the runtime, which stays the lock
on what is done (decided 2026-11-25). Another action is a subclass of
:class:`ChainAction` and an entry in :data:`ACTIONS`, without a change to
the rest of the agent. See docs/mailbox-agents/concept/agent-categorization.md.
"""

from __future__ import annotations

from abc import ABC, abstractmethod
from typing import Any, ClassVar, Literal

from pydantic import BaseModel, ConfigDict, Field, field_validator

from ...contract import (
    KEYWORD_FORM,
    Action,
    ActionRequest,
    Placed,
    folder_path,
    from_top,
)

__all__ = [
    "ACTIONS",
    "STAGES",
    "ChainAction",
    "Keyword",
    "Move",
    "MoveBelow",
    "Stage",
    "held_by_stage",
]

# The stage of an entry as written. keyword is the word of the middle stage
# before 2026-11-27: it is kept as written, so the digest of a list, its
# version, stays the same, and it ranks as suggest.
Stage = Literal["shadow", "suggest", "keyword", "full"]

# The stages from the least to the most an agent may do.
STAGES: tuple[Stage, ...] = ("shadow", "suggest", "full")

# The word each stage of an entry stands for.
_RANKS_AS: dict[Stage, Stage] = {"keyword": "suggest"}

# The least stage that carries out each action, as the executor's table
# says: a keyword from ``suggest`` on, a folder and a move in ``full``.
_RUNS_FROM: dict[Action, Stage] = {
    Action.ADD_KEYWORD: "suggest",
    Action.REMOVE_KEYWORD: "suggest",
    Action.CREATE_FOLDER: "full",
    Action.MOVE_TO_FOLDER: "full",
}


def held_by_stage(stage: Stage | None, action: Action) -> bool:
    """Whether an entry with ``stage`` holds ``action``: its stage is below
    the one that carries the action out. A stage only lowers what the stage
    of the agent allows, it never raises it."""
    if stage is None:
        return False
    ranked = _RANKS_AS.get(stage, stage)
    return STAGES.index(ranked) < STAGES.index(_RUNS_FROM[action])


class Params(BaseModel):
    """The value of an entry, as an action reads it."""

    model_config = ConfigDict(frozen=True, extra="forbid")


class FolderParams(Params):
    target: str = Field(min_length=1, max_length=200)

    @field_validator("target")
    @classmethod
    def _target(cls, value: str) -> str:
        return folder_path(value)


class KeywordParams(Params):
    target: str = Field(min_length=1, max_length=100)

    @field_validator("target")
    @classmethod
    def _target(cls, value: str) -> str:
        if not KEYWORD_FORM.fullmatch(value) or not value.startswith("agent-"):
            raise ValueError(
                "a keyword is agent- and lower case letters, digits and dashes"
            )
        return value


def _target_of(params: Params) -> str:
    """The target of a folder or a keyword entry."""
    return str(params.model_dump()["target"])


class ChainAction(ABC):
    """One action of ``then``: its name, the form of its value, the
    actions of the contract it asks for, and whether a category the model
    chose may set it off by itself."""

    name: ClassVar[str]
    params: ClassVar[type[Params]]
    primitives: ClassVar[frozenset[Action]]
    # A move only on a group the owner set to act by its topic: else it is
    # recorded. A keyword may follow a choice of the model.
    by_model: ClassVar[bool]

    def parse(self, value: Any) -> dict[str, Any]:
        """The value of an entry, checked: a text is its target."""
        found = value if isinstance(value, dict) else {"target": value}
        return self.params.model_validate(found).model_dump()

    @abstractmethod
    def requests(
        self, params: Params, placed: Placed, *, held: bool, why: str
    ) -> list[ActionRequest]:
        """The requests for the executor, held when ``held``."""


class Move(ChainAction):
    """Move the message into a folder, made first with each folder above
    it when missing."""

    name = "move"
    params = FolderParams
    primitives = frozenset({Action.CREATE_FOLDER, Action.MOVE_TO_FOLDER})
    by_model = False

    def requests(
        self, params: Params, placed: Placed, *, held: bool, why: str
    ) -> list[ActionRequest]:
        target = _target_of(params)
        found = [
            ActionRequest(
                Action.CREATE_FOLDER, placed.ref, folder=path, why=why, held=held
            )
            for path in from_top(target)
        ]
        found.append(
            ActionRequest(
                Action.MOVE_TO_FOLDER, placed.ref, folder=target, why=why, held=held
            )
        )
        return found


class MoveBelow(ChainAction):
    """A folder below the one the message is moved into, or below the
    folder of the owner it lies in: the move goes there."""

    name = "move_below"
    params = FolderParams
    primitives = frozenset({Action.CREATE_FOLDER, Action.MOVE_TO_FOLDER})
    by_model = False

    def requests(
        self, params: Params, placed: Placed, *, held: bool, why: str
    ) -> list[ActionRequest]:
        # Joined with the move by the agent, never asked alone.
        return []


class Keyword(ChainAction):
    """Set a keyword the list names."""

    name = "keyword"
    params = KeywordParams
    primitives = frozenset({Action.ADD_KEYWORD})
    by_model = True

    def requests(
        self, params: Params, placed: Placed, *, held: bool, why: str
    ) -> list[ActionRequest]:
        target = _target_of(params)
        return [
            ActionRequest(
                Action.ADD_KEYWORD, placed.ref, keyword=target, why=why, held=held
            )
        ]


# The actions a list may name, by name.
ACTIONS: dict[str, ChainAction] = {
    action.name: action for action in (Move(), MoveBelow(), Keyword())
}
