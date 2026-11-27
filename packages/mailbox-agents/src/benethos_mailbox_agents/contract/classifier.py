"""``Classifier``: an agent that reads a message and answers a question
about it, by rules or with the model. Every agent that reads the text of
a mail is one. Its counterpart is the :class:`~.actor.Actor`, which sees
where a message lies and never asks a model. See
docs/mailbox-agents/concept/agent-contract.md."""

from __future__ import annotations

from ..errors import ContractError
from .agent import Action, Agent

__all__ = ["Classifier"]


class Classifier(Agent):
    """An agent that reads a message and answers a question about it, with
    rules or with the model. A classifier drafts no forward: what it
    reads may hold what a forward would carry away."""

    @classmethod
    def validate_definition(cls) -> None:
        super().validate_definition()
        if Action.DRAFT_FORWARD in cls.actions:
            raise ContractError(f"{cls.name}: a classifier drafts no forward")
