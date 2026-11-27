"""The actions an agent may ask for, how each is taken back, and what
each stage carries out. See docs/mailbox-agents/concept/agent-contract.md.
"""

from __future__ import annotations

from dataclasses import dataclass, field
from enum import StrEnum
from typing import Literal

from ..records import MessageRef
from ..settings import FORMER_STAGES

__all__ = [
    "FORMER_STAGES",
    "REVERSED_BY",
    "STAGE_ALLOWS",
    "Action",
    "ActionRequest",
    "ForwardForm",
]


class Action(StrEnum):
    """The actions that exist. A new one is added to
    docs/mailbox-agents/concept/agent-contract.md first, with how it is taken back."""

    ADD_KEYWORD = "add_keyword"
    REMOVE_KEYWORD = "remove_keyword"
    MOVE_TO_FOLDER = "move_to_folder"
    CREATE_FOLDER = "create_folder"
    DRAFT_FORWARD = "draft_forward"


# How each action is taken back. A move is taken back by a move to the
# folder recorded before it. A folder made is taken back by the owner, as
# deleting a folder needs a right no agent has: None. So is a forward
# drafted, which lies in the owner's drafts folder.
REVERSED_BY: dict[Action, Action | None] = {
    Action.ADD_KEYWORD: Action.REMOVE_KEYWORD,
    Action.REMOVE_KEYWORD: Action.ADD_KEYWORD,
    Action.MOVE_TO_FOLDER: Action.MOVE_TO_FOLDER,
    Action.CREATE_FOLDER: None,
    Action.DRAFT_FORWARD: None,
}


# The forms of a forward drafted: the message quoted with its attachments,
# or the message as a file.
ForwardForm = Literal["inline", "attachment"]


@dataclass(frozen=True, slots=True)
class ActionRequest:
    """One action an agent asks the runtime to take.

    ``keyword`` for the keyword actions, ``folder`` for a move and for a
    folder to make: the path of the folder, ``/`` between the names. The
    runtime resolves it, refuses a move into a folder that does not exist,
    and makes only a folder the agent may make, see :meth:`Agent.may_create`.
    ``held`` asks for the action to be recorded only, as in ``shadow``,
    whatever the stage: for a group or rule its configuration holds.
    ``recipients`` and ``forward_as`` for a forward drafted: the
    addresses, each one :meth:`Agent.recipients` names, and the form,
    ``inline`` or ``attachment``.
    """

    action: Action
    ref: MessageRef
    keyword: str | None = None
    folder: str | None = None
    why: str = field(default="", compare=False)
    held: bool = False
    recipients: tuple[str, ...] = ()
    forward_as: ForwardForm | None = None


# What each stage carries out. The rest is recorded only. The word a stage
# had before, FORMER_STAGES, stands for the stage it is read as.
STAGE_ALLOWS: dict[str, frozenset[Action]] = {
    "shadow": frozenset(),
    # What the owner sees and takes back in one step: a keyword, a forward
    # in the drafts folder.
    "suggest": frozenset(
        {Action.ADD_KEYWORD, Action.REMOVE_KEYWORD, Action.DRAFT_FORWARD}
    ),
    "full": frozenset(Action),
}
