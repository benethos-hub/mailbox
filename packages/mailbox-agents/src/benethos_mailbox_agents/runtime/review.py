"""What an agent decided and did, message by message, read from its
state file for a person to review: the command ``report`` prints it, the
cockpit shows it.

The state file holds ids only, so subject and sender are fetched from the
mailbox service at the moment of reading and are never stored.
"""

from __future__ import annotations

from dataclasses import dataclass, field

from ..contract import Reader
from ..errors import MailboxRefusedError
from ..records import Decision, MailMessage, StepResult
from ..store import ActionRow, MessageRow, Store

__all__ = ["Entry", "collect"]


@dataclass
class Entry:
    """One message of the report."""

    row: MessageRow
    message: MailMessage | None
    decision: Decision | None
    model: str
    baseline: Decision | None
    actions: list[ActionRow] = field(default_factory=list)


def _latest(steps: list[StepResult], step: str) -> tuple[Decision | None, str]:
    """The decision of the last ``step`` of ``steps``, and its model."""
    found = [s for s in steps if s.step == step]
    if not found:
        return None, ""
    return Decision.model_validate(found[-1].result), found[-1].model


async def collect(
    store: Store,
    mailbox: Reader | None,
    *,
    limit: int,
    state: str | None = None,
) -> list[Entry]:
    """The newest ``limit`` messages, in ``state`` if named, each with its
    subject and sender fetched now unless ``mailbox`` is None."""
    entries = []
    for row in store.messages(state, limit):
        message = None
        if mailbox is not None:
            try:
                message = await mailbox.message(row.ref)
            except MailboxRefusedError:
                message = None
        steps = store.steps(row.ref)
        decision, model = _latest(steps, "decision")
        baseline, _ = _latest(steps, "baseline")
        entries.append(
            Entry(row, message, decision, model, baseline, store.actions(row.ref))
        )
    return entries
