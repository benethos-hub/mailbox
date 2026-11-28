"""What an agent decided and did, message by message, read from its
state file for a person to review: the command ``report`` prints it, the
cockpit shows it.

The state file holds ids only, so subject and sender are fetched from the
mailbox service at the moment of reading and are never stored.
"""

from __future__ import annotations

from dataclasses import dataclass, field

from pydantic import ValidationError

from ..contract import Reader
from ..errors import MailboxRefusedError
from ..records import Decision, MailMessage, StepResult
from ..store import ActionRow, MessageRow, Store

__all__ = ["Entry", "collect", "entry"]


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
    """The decision of the last ``step`` of ``steps``, and its model. One
    that does not fit, such as a decision of a newer version, is none: the
    message shows without it."""
    found = [s for s in steps if s.step == step]
    if not found:
        return None, ""
    try:
        return Decision.model_validate(found[-1].result), found[-1].model
    except ValidationError:
        return None, found[-1].model


async def entry(store: Store, mailbox: Reader | None, row: MessageRow) -> Entry:
    """The message of ``row`` with what the agent decided and did, its
    subject and sender fetched now unless ``mailbox`` is None."""
    message = None
    if mailbox is not None:
        try:
            message = await mailbox.message(row.ref)
        except MailboxRefusedError:
            message = None
    steps = store.steps(row.ref)
    decision, model = _latest(steps, "decision")
    baseline, _ = _latest(steps, "baseline")
    return Entry(row, message, decision, model, baseline, store.actions(row.ref))


async def collect(
    store: Store,
    mailbox: Reader | None,
    *,
    limit: int,
    state: str | None = None,
) -> list[Entry]:
    """The newest ``limit`` messages, in ``state`` if named, each with its
    subject and sender fetched now unless ``mailbox`` is None."""
    return [await entry(store, mailbox, row) for row in store.messages(state, limit)]
