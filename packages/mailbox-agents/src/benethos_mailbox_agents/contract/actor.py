"""``Actor``: an agent that acts on mail by its keywords, by a list its
owner wrote, without a model and without reading what a mail says.

An actor sees a message as :class:`Placed` alone: where it lies, which
keywords it carries, the sender check, and whether it came from some
addresses. It writes two narrow methods, :meth:`Actor.rule` and
:meth:`Actor.act`, and says which keywords it waits for. The base puts
them together into the methods of :class:`Agent`, so an actor runs
through the step runner and the executor as any agent does. The code
keeps the narrow view, not a right of the mailbox service: the service
has no right to read the metadata of a mail alone. See
docs/mailbox-agents/concept/agent-contract.md.
"""

from __future__ import annotations

import json
from abc import abstractmethod
from typing import ClassVar

from pydantic import BaseModel

from benethos_mailbox_common.values import secret

from ..errors import ContractError
from ..records import DISCARD_ROLES, OWN_ROLES, Decision, MailMessage
from .agent import ActionRequest, Agent, Limits, Route, Trigger
from .context import Context
from .placed import Placed

__all__ = ["PASSED_BY", "Actor", "list_version"]

# The folders an actor never acts in: the owner discarded the mail there,
# or it is the owner's own, being written or sent.
PASSED_BY = DISCARD_ROLES | OWN_ROLES

# The methods the base puts together from rule and act. An actor that
# wrote one of them would read the mail itself or ask a model.
_PROVIDED = ("admit", "baseline", "decide", "effect", "decide_again", "refresh")


def list_version(listed: BaseModel) -> str:
    """The version of a list an actor reads, as ``list-`` and twelve
    characters of a digest of the list in JSON with sorted keys: the same
    list gives the same version, a changed one a new one."""
    normal = json.dumps(listed.model_dump(mode="json"), sort_keys=True)
    return "list-" + secret.digest(normal)[:12]


class Actor(Agent):
    """An agent that acts on mail by its keywords: no model, nothing of
    what a mail says. A new message is taken up when it carries a keyword
    the actor waits for, else it ends ``skipped``, and an update that
    shows it with one takes it up again. ``backfill`` takes up the mail
    that carries one already."""

    limits: ClassVar[Limits] = Limits(model_calls_per_message=0, model_calls_per_day=0)
    triggers: ClassVar[Trigger] = Trigger(
        routes={"message.created": Route.DECIDE, "message.updated": Route.OBSERVE}
    )

    # -- to write --------------------------------------------------------------

    @abstractmethod
    def waits_for(self, keyword: str) -> bool:
        """Whether its list waits for ``keyword``, case aside."""

    @abstractmethod
    def rule(self, placed: Placed) -> Decision:
        """Which rule of its list holds for the message: a decision of the
        source ``baseline``, labelled ``rule-<n>`` by the place of the rule
        from 1, or ``none``. Code only."""

    @abstractmethod
    def act(self, decision: Decision, placed: Placed) -> list[ActionRequest]:
        """The actions that follow from ``decision`` for the message."""

    def takes(self, placed: Placed) -> bool:
        """Whether the message is one for the actor at all, beside the
        keyword it waits for. Yes by default."""
        return True

    # -- provided ----------------------------------------------------------------

    def admit(self, message: MailMessage) -> bool:
        """A message that carries a keyword the actor waits for, lies in
        none of :data:`PASSED_BY`, and that :meth:`takes` takes."""
        placed = Placed.of(message)
        if not any(self.waits_for(keyword) for keyword in placed.keywords):
            return False
        if any(folder.role in PASSED_BY for folder in placed.folders):
            return False
        return self.takes(placed)

    def baseline(self, message: MailMessage) -> Decision:
        return self.rule(Placed.of(message))

    async def decide(self, message: MailMessage, context: Context) -> Decision:
        return self.rule(Placed.of(message))

    async def effect(
        self, decision: Decision, message: MailMessage, context: Context
    ) -> list[ActionRequest]:
        return self.act(decision, Placed.of(message))

    def decide_again(self, message: MailMessage) -> bool:
        """An update that shows a message the actor admits now: decided
        again, as a keyword set since may change which rule holds."""
        return self.admit(message)

    def refresh(self, stored: Decision, message: MailMessage) -> Decision:
        """The rule worked out anew: a decision of an actor is code only,
        so the one stored does not count."""
        return self.rule(Placed.of(message))

    def asks_model(self) -> bool:
        return False

    @classmethod
    def validate_definition(cls) -> None:
        """Beside the rules of every agent: no model call in the limits,
        and none of the methods the base puts together written anew."""
        super().validate_definition()
        if cls.limits.model_calls_per_message or cls.limits.model_calls_per_day:
            raise ContractError(f"{cls.name}: an actor asks no model")
        written = [
            name for name in _PROVIDED if getattr(cls, name) is not getattr(Actor, name)
        ]
        if written:
            raise ContractError(
                f"{cls.name}: an actor writes rule and act, not {', '.join(written)}"
            )
