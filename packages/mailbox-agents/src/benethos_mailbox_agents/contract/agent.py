"""``Agent``: the base every agent implements, and what it declares.

Every agent package defines exactly one concrete subclass in its
``agent.py``. The class attributes are validated when the class is
instantiated, so a mistake in a declaration stops the process at its
start rather than at the first message. See
docs/mailbox-agents/concept/agent-contract.md.
"""

from __future__ import annotations

import re
from abc import ABC, abstractmethod
from collections.abc import Mapping
from dataclasses import dataclass, field
from datetime import datetime
from enum import StrEnum
from typing import ClassVar

from ..errors import ContractError
from ..records import (
    EVENTS,
    Decision,
    Event,
    EventType,
    FolderRef,
    MailMessage,
    MessageRef,
)
from ..settings import KEYWORD_FORM, Settings
from .context import Context

__all__ = [
    "NAME_PATTERN",
    "REVERSED_BY",
    "Action",
    "ActionRequest",
    "Agent",
    "Limits",
    "Requires",
    "Route",
    "Shown",
    "Trigger",
]

NAME_PATTERN = re.compile(r"^[a-z][a-z0-9_]*$")


class Action(StrEnum):
    """The actions that exist. A new one is added to
    docs/mailbox-agents/concept/agent-contract.md first, with how it is taken back."""

    ADD_KEYWORD = "add_keyword"
    REMOVE_KEYWORD = "remove_keyword"
    MOVE_TO_FOLDER = "move_to_folder"
    CREATE_FOLDER = "create_folder"


# How each action is taken back. A move is taken back by a move to the
# folder recorded before it. A folder made is taken back by the owner, as
# deleting a folder needs a right no agent has: None.
REVERSED_BY: dict[Action, Action | None] = {
    Action.ADD_KEYWORD: Action.REMOVE_KEYWORD,
    Action.REMOVE_KEYWORD: Action.ADD_KEYWORD,
    Action.MOVE_TO_FOLDER: Action.MOVE_TO_FOLDER,
    Action.CREATE_FOLDER: None,
}


class Route(StrEnum):
    """What the runtime does with an event an agent selected.

    ``decide`` records the message as ``pending`` and runs the steps once
    per message, prompt version and model. ``observe`` fetches the message
    and asks :meth:`Agent.observe` at once, with no model and no record of
    its own, for an event that may come many times for one message.
    """

    DECIDE = "decide"
    OBSERVE = "observe"


@dataclass(frozen=True, slots=True)
class Trigger:
    """The feed events an agent wants, each with the route it takes, and
    whether it wants the tick."""

    routes: Mapping[EventType, Route]
    tick: bool = False

    @property
    def events(self) -> frozenset[EventType]:
        """The feed events the agent wants."""
        return frozenset(self.routes)


@dataclass(frozen=True, slots=True)
class Limits:
    """Model calls an agent may make, per message and per day."""

    model_calls_per_message: int = 1
    model_calls_per_day: int = 2000
    # The longest quote or value an answer may hold. A longer one is
    # refused as not fitting the schema, so an answer cannot copy the mail
    # into the state file. Checked after parsing: the schema sent to the
    # model does not change.
    answer_text: int = 300


@dataclass(frozen=True, slots=True)
class Requires:
    """Settings that must be present before the agent starts, by their
    field names in :class:`~benethos_mailbox_agents.settings.Settings`."""

    settings: tuple[str, ...] = ()


@dataclass(frozen=True, slots=True)
class ActionRequest:
    """One action an agent asks the runtime to take.

    ``keyword`` for the keyword actions, ``folder`` for a move and for a
    folder to make: the path of the folder, ``/`` between the names. The
    runtime resolves it, refuses a move into a folder that does not exist,
    and makes only a folder the agent may make, see :meth:`Agent.may_create`.
    ``held`` asks for the action to be recorded only, as in ``shadow``,
    whatever the stage: for a group or rule its configuration holds.
    """

    action: Action
    ref: MessageRef
    keyword: str | None = None
    folder: str | None = None
    why: str = field(default="", compare=False)
    held: bool = False


@dataclass(frozen=True, slots=True)
class ShownAction:
    """An action of a message of a report: what it was, and whether it
    was carried out."""

    action: Action
    done: bool


@dataclass(frozen=True, slots=True)
class Shown:
    """One message of a report, as an agent's summary sees it: its
    sender's address, fetched for the report, its decision, and its
    actions."""

    sender: str | None
    decision: Decision
    actions: tuple[ShownAction, ...] = ()


class Agent(ABC):
    """Base class of every agent. See docs/mailbox-agents/concept/agent-contract.md."""

    name: ClassVar[str]
    version: ClassVar[str]
    description: ClassVar[str]
    triggers: ClassVar[Trigger]
    actions: ClassVar[frozenset[Action]]
    limits: ClassVar[Limits] = Limits()
    requires: ClassVar[Requires] = Requires()
    # The keyword the agent sets when MAILBOX_AGENTS_KEYWORD is unset.
    default_keyword: ClassVar[str]
    # The version of the prompt the model step runs under. A step stored
    # under the same message, prompt version and model is not run again.
    # Read from the instance: an agent whose decision rests on a list it
    # reads sets it from that list.
    prompt_version: str = ""
    # Whether a message that carries the agent's keyword and that its state
    # file does not know is skipped after the fetch, before baseline and
    # model: it was marked before this state file, by the agent or by a
    # person, and is neither asked about nor moved again. A person takes
    # the keyword off to have it looked at again. Off by default.
    skip_marked: ClassVar[bool] = False
    # The labels and field names an evaluation report names in plain text.
    # Any other, such as the name of a group the owner chose, becomes
    # label-<n> or field-<n> there, as a report is versioned. None by
    # default.
    report_labels: ClassVar[frozenset[str]] = frozenset()
    report_fields: ClassVar[frozenset[str]] = frozenset()

    def __init__(self, settings: Settings) -> None:
        self.validate_definition()
        self.settings = settings
        self.keyword = settings.keyword or self.default_keyword

    # -- to implement ---------------------------------------------------------

    def select(self, event: Event) -> Route | None:
        """Whether this event concerns the agent, and how: the route its
        triggers name for the type of the event. Code only."""
        return self.triggers.routes.get(event.type)

    def admit(self, message: MailMessage) -> bool:
        """After the fetch: whether the message is one for this agent, such
        as one in the inbox. Code only. A message not admitted is
        ``skipped``."""
        return True

    @abstractmethod
    def baseline(self, message: MailMessage) -> Decision:
        """The question answered by rules."""

    @abstractmethod
    async def decide(self, message: MailMessage, context: Context) -> Decision:
        """The question answered with the model, at most as many calls as
        the limits allow."""

    @abstractmethod
    async def effect(
        self, decision: Decision, message: MailMessage, context: Context
    ) -> list[ActionRequest]:
        """The actions that follow from a decision the evidence check let
        through."""

    async def observe(
        self, message: MailMessage, context: Context
    ) -> list[ActionRequest]:
        """For an event routed to ``observe``: the actions it calls for."""
        return []

    async def tick(self, now: datetime, context: Context) -> list[ActionRequest]:
        """For agents with deadlines: the actions that are due."""
        return []

    def summarize(self, shown: list[Shown]) -> list[str]:
        """For ``report``: lines about the messages shown, each with its
        sender's address, its decision and its actions. Nothing by
        default."""
        return []

    def backfill_folder(self, folder: FolderRef) -> bool:
        """Whether ``backfill`` takes up the messages of ``folder`` besides
        those of the inbox and of sent mail, such as a folder the agent
        looks in. None by default."""
        return False

    def folders_needed(self) -> tuple[str, ...]:
        """The folders the agent's configuration names and expects to be
        there, which ``status`` looks up in the mailbox service. A missing
        one does not stop the start: another agent may make it later.
        None by default."""
        return ()

    def describe_folders(self, folders: Mapping[str, FolderRef]) -> list[str]:
        """For ``status``: a line for each folder of an account that matters
        to the agent, such as one it looks in and what it does with an
        invoice there. ``folders`` are the account's folders by path. Folder
        names only, never anything of a mail. Asked only of an agent whose
        :meth:`folders_needed` names one. None by default."""
        return []

    def may_create(self, path: str, folders: Mapping[str, FolderRef]) -> bool:
        """Whether the runtime may make the folder at ``path`` for this
        agent: one its configuration names, such as a folder of its list or
        one above it. ``folders`` are the account's folders by path, for an
        agent whose answer depends on the folder above, such as its role.
        Code only, never from an answer of the model. None by default."""
        return False

    def prepare(self) -> None:
        """Read what the agent needs beyond its settings, such as a list
        in a file, and raise a ConfigError if it is wrong. Called once
        before the agent starts, and by ``status``."""
        return None

    def asks_model(self) -> bool:
        """Whether this agent, as configured, asks a model, so it needs the
        gateway. Asked after :meth:`prepare`. By default whether its limits
        allow a call."""
        return self.limits.model_calls_per_message > 0

    # -- provided -------------------------------------------------------------

    @classmethod
    def validate_definition(cls) -> None:
        """Raise a :class:`ContractError` for a declaration that breaks the
        contract."""
        for attr in (
            "name",
            "version",
            "description",
            "triggers",
            "actions",
            "default_keyword",
        ):
            if not hasattr(cls, attr):
                raise ContractError(f"{cls.__name__}: {attr} must be declared")
        _check_identity(cls)
        _check_declarations(cls)


def _check_identity(cls: type[Agent]) -> None:
    if not NAME_PATTERN.match(cls.name):
        raise ContractError(
            f"{cls.__name__}: the name {cls.name!r} is not lowercase letters, "
            "digits and _"
        )
    package = cls.__module__.split(".")
    if len(package) >= 2 and package[-1] == "agent" and package[-2] != cls.name:
        raise ContractError(
            f"{cls.__name__}: the name {cls.name!r} differs from its package "
            f"{package[-2]!r}"
        )
    if not cls.version or not cls.description:
        raise ContractError(f"{cls.name}: version and description must not be empty")


def _check_declarations(cls: type[Agent]) -> None:
    unknown = set(cls.triggers.events) - EVENTS
    if unknown:
        raise ContractError(f"{cls.name}: unknown events {sorted(unknown)}")
    if not cls.triggers.events and not cls.triggers.tick:
        raise ContractError(f"{cls.name}: triggers name no event and no tick")
    if not isinstance(cls.actions, frozenset) or not all(
        isinstance(a, Action) for a in cls.actions
    ):
        raise ContractError(f"{cls.name}: actions must name actions of the list")
    if cls.limits.model_calls_per_message < 0 or cls.limits.model_calls_per_day < 0:
        raise ContractError(f"{cls.name}: limits must not be negative")
    fields = set(Settings.model_fields)
    wrong = [name for name in cls.requires.settings if name not in fields]
    if wrong:
        raise ContractError(f"{cls.name}: requires unknown settings {wrong}")
    keyword = cls.default_keyword
    if not KEYWORD_FORM.fullmatch(keyword or ""):
        raise ContractError(
            f"{cls.name}: the default keyword is not one word of lower case "
            "letters, digits and dashes"
        )
