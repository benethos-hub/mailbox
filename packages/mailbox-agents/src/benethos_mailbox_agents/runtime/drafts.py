"""What the executor checks of a forward drafted, ``draft_forward``, and
how it plans one. See docs/mailbox-agents/concept/agent-contract.md.

Taken only when the agent declares it, on an account it works on, to
addresses its :meth:`~benethos_mailbox_agents.contract.Agent.recipients`
names and to none other, ``inline`` or as an ``attachment``. Never for a
message in the drafts or in sent mail, once per message, and no more per
day than the agent's limits allow. The state file records the form and
the addresses. A message of a refusal names neither: they are the owner's
text.
"""

from __future__ import annotations

from datetime import datetime

from ..contract import Action, ActionRequest, Agent
from ..errors import ActionRefusedError
from ..records import MailMessage
from ..store import Store
from .model import start_of_day
from .outcomes import Plan

__all__ = ["FORMS", "admissible", "plan", "unsettled"]

# The forms of a forward, as the mailbox service takes them.
FORMS = frozenset({"inline", "attachment"})

# The folders a message to forward may not lie in: the owner's own mail,
# being written or sent.
_OWN_ROLES = frozenset({"drafts", "sent"})


def admissible(agent: Agent, request: ActionRequest) -> None:
    """Refuse a forward to an address the agent does not name, or in a
    form there is none of. Declared and on its account the executor
    checked before."""
    if not request.recipients:
        raise ActionRefusedError("a forward names no recipient")
    allowed = agent.recipients()
    if any(address.casefold() not in allowed for address in request.recipients):
        raise ActionRefusedError("a forward goes only to the agent's recipients")
    if request.forward_as not in FORMS:
        raise ActionRefusedError("a forward is inline or an attachment")


def unsettled(store: Store, request: ActionRequest) -> bool:
    """Whether a forward of the message is recorded and not taken: one
    whose answer may not have come, so the service is asked before a
    second draft."""
    return any(
        row.action == Action.DRAFT_FORWARD.value and not row.executed
        for row in store.actions(request.ref)
    )


def plan(
    agent: Agent,
    store: Store,
    request: ActionRequest,
    message: MailMessage,
    now: datetime,
) -> Plan | None:
    """The forward as planned: its form and addresses as the argument,
    nothing before it. None when a forward of the message was drafted
    already. Refused for a message in the drafts or sent mail, and past
    the drafts of the day."""
    if any(folder.role in _OWN_ROLES for folder in message.folders):
        raise ActionRefusedError("no forward of a message in the drafts or sent mail")
    done = any(
        row.action == Action.DRAFT_FORWARD.value and row.executed
        for row in store.actions(request.ref)
    )
    if done:
        return None
    today = store.executed_since(Action.DRAFT_FORWARD.value, start_of_day(now))
    if today >= agent.limits.drafts_per_day:
        raise ActionRefusedError("the forwards of the day are drafted")
    addresses = ",".join(sorted(a.casefold() for a in request.recipients))
    argument = f"{request.forward_as}:{addresses}"
    return Plan(argument, {}, argument)
