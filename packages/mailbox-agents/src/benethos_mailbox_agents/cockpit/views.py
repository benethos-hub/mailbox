"""What a page of the cockpit shows, read from the state files.

Each state file is opened read-only for one request and closed after it,
and read through the methods of the store alone. A file that cannot be
read, or is of a newer schema, is a row with its reason, never an error
of the page. Everything from a state file or a mail is foreign text:
each such value passes ``text_values.escaped`` here, before a page draws
it, and the pages escape it once more as HTML.
"""

from __future__ import annotations

import functools
from collections.abc import Callable
from contextlib import AbstractAsyncContextManager
from dataclasses import dataclass, replace
from datetime import datetime, timedelta
from urllib.parse import quote

from benethos_mailbox_common.values import text as text_values

from ..contract import Actor, Reader, discover
from ..errors import (
    ConfigError,
    MailboxAgentError,
    StateFileError,
    UnavailableError,
)
from ..records import Decision, MailMessage, MessageRef, OpenItem, Profile
from ..runtime.health import window_of
from ..runtime.review import Entry, collect, entry
from ..store import ActionRow, Store
from .sources import Instance

__all__ = [
    "Act",
    "Count",
    "Detail",
    "Fact",
    "Item",
    "MailboxFactory",
    "Quote",
    "UNREADABLE",
    "Result",
    "Results",
    "Row",
    "StepLine",
    "message",
    "results",
    "row",
    "unreadable",
]

# Opens the mailbox service for the length of one request.
MailboxFactory = Callable[[], AbstractAsyncContextManager[Reader]]

# How far back the overview counts the decisions per label.
LABELS_SINCE = timedelta(hours=24)
# What a state that cannot be read raises: a row with its reason.
UNREADABLE = (ConfigError, StateFileError, UnavailableError)


def _e(text: str | None) -> str:
    return text_values.escaped(text or "")


def _link(value: str) -> str:
    """``value`` as one part of an address, a slash in it as well."""
    return quote(value, safe="")


@dataclass(frozen=True, slots=True)
class Fact:
    name: str
    value: str


@dataclass(frozen=True, slots=True)
class Count:
    name: str
    count: int


@dataclass(frozen=True, slots=True)
class Item:
    """An open item of an agent that follows a message."""

    account_id: str
    message_id: str
    opened: datetime
    due: datetime
    keyword_set: bool


@dataclass(frozen=True, slots=True)
class Row:
    """One instance: a line of the overview, and the head of its page.
    ``link`` is its name as a part of an address."""

    name: str
    link: str
    agent: str
    kind: str
    stage: str
    version: str
    state: str
    progress: datetime | None
    counts: tuple[Count, ...] = ()
    labels: tuple[Count, ...] = ()
    model_calls: int = 0
    due: int = 0
    problem: str | None = None
    facts: tuple[Fact, ...] = ()
    items: tuple[Item, ...] = ()


@dataclass(frozen=True, slots=True)
class Act:
    action: str
    argument: str
    stage: str
    executed: bool
    at: datetime


@dataclass(frozen=True, slots=True)
class Result:
    """One message an agent took up, with subject and sender when the
    mailbox service could be asked. ``link`` is the address of its page
    below the page of its instance, made from the ids as they are."""

    account_id: str
    message_id: str
    link: str
    created: datetime
    state: str
    sender: str | None
    subject: str | None
    label: str | None
    source: str
    model: str
    refused: str | None
    baseline: str | None
    actions: tuple[Act, ...]


@dataclass(frozen=True, slots=True)
class Results:
    """The newest messages of an instance. ``unanswered``: the mailbox
    service was asked and did not answer, so they show their ids
    alone."""

    items: tuple[Result, ...]
    unanswered: bool = False


@dataclass(frozen=True, slots=True)
class Quote:
    field: str
    value: str
    quote: str
    found: bool | None


@dataclass(frozen=True, slots=True)
class StepLine:
    step: str
    prompt_version: str
    model: str
    tokens_in: int
    tokens_out: int
    duration_ms: int
    at: datetime


@dataclass(frozen=True, slots=True)
class Detail:
    """One result with everything the state file holds of it."""

    result: Result
    fields: tuple[Fact, ...]
    details: tuple[Fact, ...]
    evidence: tuple[Quote, ...]
    steps: tuple[StepLine, ...]
    unanswered: bool = False


@functools.cache
def _kinds() -> dict[str, tuple[str, str]]:
    """The kind and the description of each agent this version knows."""
    return {
        name: ("actor" if issubclass(cls, Actor) else "classifier", cls.description)
        for name, cls in discover().items()
    }


def _facts(profile: Profile, description: str) -> tuple[Fact, ...]:
    accounts = ", ".join(profile.accounts) or "every account of the user"
    found = (
        ("Agent", profile.agent),
        ("Instance", profile.instance or "none"),
        ("What it does", description),
        ("Version of the agent", profile.agent_version),
        ("Version of the package", profile.package_version),
        ("Stage", profile.stage),
        ("Accounts", accounts),
        ("Keyword", profile.keyword),
        ("Seconds between polls", f"{profile.poll_seconds:g}"),
        ("Seconds a model call may take", f"{profile.gateway_timeout_seconds:g}"),
        ("Model alias", profile.model_alias or "none"),
        ("Prompt version", profile.prompt_version or "none"),
        ("Started", profile.started.isoformat(timespec="seconds")),
    )
    return tuple(Fact(name, _e(value)) for name, value in found)


def _state(
    found: Instance, profile: Profile | None, progress: datetime | None, now: datetime
) -> str:
    if found.stopped():
        return "stopped"
    if profile is None:
        return "no profile yet"
    window = window_of(profile.poll_seconds, profile.gateway_timeout_seconds)
    if progress is not None and now - progress <= window:
        return "healthy"
    return "silent"


def _item(item: OpenItem) -> Item:
    return Item(
        _e(item.ref.account_id),
        _e(item.ref.message_id),
        item.opened,
        item.due,
        item.keyword_set,
    )


def row(file: Instance, now: datetime) -> Row:
    """The instance ``file`` as the overview and its page show it."""
    try:
        with file.open() as store:
            profile = store.profile()
            progress = store.progress()
            counts = store.counts()
            labels = store.labels_since(now - LABELS_SINCE)
            day = now.replace(hour=0, minute=0, second=0, microsecond=0)
            calls = store.model_calls_since(day)
            due = len(store.due_items(now))
            items = tuple(_item(item) for item in store.open_items())
    except UNREADABLE as exc:
        return Row(
            name=_e(file.name),
            link=_link(file.name),
            agent="",
            kind="",
            stage="",
            version="",
            state="unreadable",
            progress=None,
            problem=_e(exc.message),
        )
    agent, kind, description, stage, version = _e(file.name), "", "", "", ""
    facts: tuple[Fact, ...] = ()
    if profile is not None:
        agent, stage, version = profile.agent, profile.stage, profile.agent_version
        kind, description = _kinds().get(agent, ("unknown to this version", ""))
        facts = _facts(profile, description)
    return Row(
        name=_e(file.name),
        link=_link(file.name),
        agent=_e(agent),
        kind=kind,
        stage=_e(stage),
        version=_e(version),
        state=_state(file, profile, progress, now),
        progress=progress,
        counts=tuple(Count(state, count) for state, count in counts.items()),
        labels=tuple(Count(_e(label), count) for label, count in labels.items()),
        model_calls=calls,
        due=due,
        facts=facts,
        items=items,
    )


def _sender(message: MailMessage | None) -> str | None:
    if message is None or message.sender is None:
        return None
    sender = message.sender
    return _e(f"{sender.name} <{sender.email}>" if sender.name else sender.email)


def _act(row: ActionRow) -> Act:
    return Act(_e(row.action), _e(row.argument), _e(row.stage), row.executed, row.at)


def _result(entry: Entry) -> Result:
    decision: Decision | None = entry.decision
    return Result(
        account_id=_e(entry.row.ref.account_id),
        message_id=_e(entry.row.ref.message_id),
        link=f"{_link(entry.row.ref.account_id)}/{_link(entry.row.ref.message_id)}",
        created=entry.row.created,
        state=entry.row.state,
        sender=_sender(entry.message),
        subject=None if entry.message is None else _e(entry.message.subject),
        label=None if decision is None else _e(decision.label),
        source="" if decision is None else decision.source,
        model=_e(entry.model),
        refused=None
        if decision is None or decision.refused is None
        else _e(decision.refused),
        baseline=None if entry.baseline is None else _e(entry.baseline.label),
        actions=tuple(_act(action) for action in entry.actions),
    )


def unreadable(found: Row, exc: MailboxAgentError) -> Row:
    """``found``, whose state failed after its row was read, with the
    reason."""
    return replace(found, state="unreadable", problem=_e(exc.message))


async def _entries(
    store: Store, mailbox: MailboxFactory | None, *, limit: int, state: str | None
) -> tuple[list[Entry], bool]:
    """The entries, and whether the mailbox service was asked and did
    not answer: then they are read again with their ids alone."""
    if mailbox is not None:
        try:
            async with mailbox() as reader:
                found = await collect(store, reader, limit=limit, state=state)
            return found, False
        except MailboxAgentError:
            pass
    found = await collect(store, None, limit=limit, state=state)
    return found, mailbox is not None


async def results(
    file: Instance,
    mailbox: MailboxFactory | None,
    *,
    limit: int,
    state: str | None = None,
) -> Results:
    """The newest ``limit`` messages of ``file``, in ``state`` if named,
    with subject and sender only when ``mailbox`` is given and
    answers."""
    with file.open() as store:
        entries, unanswered = await _entries(store, mailbox, limit=limit, state=state)
    return Results(tuple(_result(entry) for entry in entries), unanswered)


def _detail(entry: Entry, steps: list[StepLine], unanswered: bool) -> Detail:
    decision = entry.decision
    fields = (
        ()
        if decision is None
        else tuple(Fact(_e(name), _e(value)) for name, value in decision.fields.items())
    )
    details = (
        ()
        if decision is None
        else tuple(
            Fact(_e(name), _e(value)) for name, value in decision.details.items()
        )
    )
    evidence = (
        ()
        if decision is None
        else tuple(
            Quote(_e(item.field), _e(item.value), _e(item.quote), item.found)
            for item in decision.evidence
        )
    )
    return Detail(_result(entry), fields, details, evidence, tuple(steps), unanswered)


async def message(
    file: Instance, ref: MessageRef, mailbox: MailboxFactory | None
) -> Detail | None:
    """One message of ``file`` with its decision, its evidence, its steps
    and its actions. None when the agent never took it up."""
    with file.open() as store:
        found = store.message(ref)
        if found is None:
            return None
        steps = [
            StepLine(
                step.step,
                _e(step.prompt_version),
                _e(step.model),
                step.tokens_in,
                step.tokens_out,
                step.duration_ms,
                step.at,
            )
            for step in store.steps(ref)
        ]
        taken, unanswered = None, False
        if mailbox is not None:
            try:
                async with mailbox() as reader:
                    taken = await entry(store, reader, found)
            except MailboxAgentError:
                unanswered = True
        if taken is None:
            taken = await entry(store, None, found)
    return _detail(taken, steps, unanswered)
