"""The report: what an agent decided and did, for its owner to review.

The state file holds ids only, so subject and sender are fetched from the
mailbox service at the moment of the report and are never stored. The
state file is opened read-only, so a report can be made while the agent
runs. It prints to stdout, for the person who asked, and nothing of it
reaches the log. See docs/mailbox-agents/concept/runtime.md.
"""

from __future__ import annotations

from dataclasses import dataclass, field

from benethos_mailbox_common.mail import addresses
from benethos_mailbox_common.values import text as text_values

from ..contract import Action, Agent, Reader, Shown, ShownAction
from ..errors import MailboxRefusedError
from ..records import Decision, MailMessage, StepResult
from ..settings import Settings
from ..store import ActionRow, MessageRow, Store, path_for
from .session import mailbox_for

__all__ = ["Entry", "collect", "render", "report", "summary"]


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


def _sender(message: MailMessage) -> str:
    if message.sender is None:
        return "(no sender)"
    return addresses.readable(message.sender.name, message.sender.email)


def _decision(decision: Decision, model: str) -> str:
    line = f"  decision: {decision.label} ({decision.source}"
    line += f", {model})" if model else ")"
    if decision.refused:
        line += f" refused: {decision.refused}"
    for name, value in sorted(decision.fields.items()):
        line += f" {name}={value}"
    for name, value in sorted(decision.details.items()):
        line += f" {name}={value}"
    return line


def _action(action: ActionRow) -> str:
    done = "done" if action.executed else "would have been done"
    return f"  action: {action.action} {action.argument} ({action.stage}: {done})"


def render(entries: list[Entry]) -> list[str]:
    """The report as lines."""
    lines: list[str] = []
    for entry in entries:
        ref = entry.row.ref
        lines.append(
            f"{entry.row.created:%Y-%m-%d %H:%M}  {ref.account_id}/{ref.message_id}"
            f"  {entry.row.state}"
        )
        if entry.message is None:
            lines.append("  (not fetched: gone from the mailbox or no service)")
        else:
            lines.append(f"  from: {_sender(entry.message)}")
            lines.append(f"  subject: {entry.message.subject or '(none)'}")
        if entry.decision is not None:
            lines.append(_decision(entry.decision, entry.model))
            for item in entry.decision.evidence:
                found = {True: "found", False: "NOT found", None: "not checked"}
                said = f'"{item.quote}"' if item.quote else "(by a rule)"
                lines.append(f"  evidence: {item.field} {said} {found[item.found]}")
        if entry.baseline is not None:
            lines.append(f"  baseline: {entry.baseline.label}")
        lines.extend(_action(action) for action in entry.actions)
        lines.append("")
    # Nothing from a mail or a model moves the cursor, sets the title or
    # starts a line of its own in the terminal.
    return [text_values.escaped(line) for line in lines]


def _actions(rows: list[ActionRow]) -> tuple[ShownAction, ...]:
    """The actions of a message as its summary sees them. A row of an
    action this version does not know is left out."""
    known = {action.value for action in Action}
    return tuple(
        ShownAction(Action(a.action), a.executed) for a in rows if a.action in known
    )


def summary(agent: Agent, entries: list[Entry], total: int | None = None) -> list[str]:
    """What the agent has to say about the messages shown. When ``total``,
    the messages there are in all, is more than were shown, a line before
    it says so: its counts cover the shown messages only."""
    shown = [
        Shown(
            sender=entry.message.sender.email
            if entry.message is not None and entry.message.sender is not None
            else None,
            decision=entry.decision,
            actions=_actions(entry.actions),
        )
        for entry in entries
        if entry.decision is not None
    ]
    lines = agent.summarize(shown)
    if lines and total is not None and total > len(entries):
        lines = [
            f"(the lines below count the {len(entries)} newest of {total} "
            f"messages, --limit {total} counts all)",
            *lines,
        ]
    return [text_values.escaped(line) for line in lines]


async def report(
    agent: Agent, settings: Settings, *, limit: int, state: str | None, offline: bool
) -> list[str]:
    """The report of ``agent``, read beside the running agent."""
    with Store.open(path_for(settings.data_dir, agent.name), read_only=True) as store:
        counts = store.counts()
        total = counts.get(state, 0) if state else sum(counts.values())
        if offline:
            entries = await collect(store, None, limit=limit, state=state)
        else:
            async with mailbox_for(settings) as mailbox:
                entries = await collect(store, mailbox, limit=limit, state=state)
    return render(entries) + summary(agent, entries, total)
