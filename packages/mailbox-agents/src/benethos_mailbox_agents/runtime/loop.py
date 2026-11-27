"""The worker loop: one pass after another, for one agent.

A pass reads the feed from the stored cursor, records each message the
agent selects for a decision as ``pending``, hands each event routed to
``observe`` to the agent at once, runs the steps of the pending messages
that are due, asks the agent on the tick what is due, and stores the
cursor last. A crash repeats work and skips no mail. A mailbox service that
is away leaves every message where it is, a gateway that is away only
those that ask a model, and the next pass waits twice as long, up to the
ceiling. A service of another version
ends the loop. See docs/mailbox-agents/concept/runtime.md.
"""

from __future__ import annotations

import asyncio
import time
from collections.abc import Callable
from datetime import date, datetime, timedelta
from typing import Protocol

from ..contract import Agent, Context, Limits, Reader, Route
from ..errors import (
    ChangesExpiredError,
    GatewayUnavailableError,
    MailboxAgentError,
    MailboxRefusedError,
    MailboxUnavailableError,
    MessageGoneError,
    ServiceVersionError,
    StateFileError,
    UnavailableError,
)
from ..logbook import feed, record, worker
from ..records import (
    MESSAGE_GONE,
    Event,
    MailMessage,
    MessageRef,
)
from ..store import Store
from ..telemetry import NO_SPANS, Spans
from .actions import Executor
from .metrics import Metrics
from .model import Asker
from .reader import ReadOnlyMailbox
from .readiness import accounts_of
from .steps import StepRunner, backoff, make_calls
from .tick import Tick
from .writer import Writer

__all__ = ["BACKFILL_ROLES", "BATCH", "Upstream", "Worker"]

# Pending messages one pass takes up at most, so a long queue still lets
# the cursor move and the health check see progress.
BATCH = 50

# The roles of the folders every backfill reads, whatever the agent: the
# inbox and sent mail. An agent names the folders it wants besides.
BACKFILL_ROLES = ("inbox", "sent")


class Upstream(Reader, Writer, Protocol):
    """What the loop needs of the mailbox service."""

    async def start(self, accounts: list[str] | None = None) -> str:
        """The state token of the feed as it is now."""

    async def changes(
        self, since: str, accounts: list[str] | None = None
    ) -> tuple[list[Event], str]:
        """The events since ``since``, and the state token after them."""

    async def recent(
        self, since: date, accounts: list[str] | None = None, *, roles: tuple[str, ...]
    ) -> list[MessageRef]:
        """The messages received since a day in the folders of ``roles``."""

    async def recent_in(
        self, account_id: str, folder_id: str, since: date
    ) -> list[MessageRef]:
        """The messages received since a day in one folder of one account."""

    async def accounts(self) -> tuple[str, ...]:
        """The ids of the accounts the user is granted."""

    async def ensure_matching(self) -> str:
        """The version of the service, once it matches the agents'."""

    def forget_folders(self) -> None:
        """Read the folders anew when next asked."""


class Worker:
    """The loop of one agent over one state file."""

    def __init__(
        self,
        *,
        agent: Agent,
        store: Store,
        mailbox: Upstream,
        gateway: Asker,
        now: Callable[[], datetime],
        spans: Spans = NO_SPANS,
    ) -> None:
        self.agent = agent
        self.settings = agent.settings
        self.store = store
        self._mailbox = mailbox
        self._now = now
        self.metrics = Metrics(
            agent.name, agent.version, agent.settings.stage, agent.instance or ""
        )
        self.executor = Executor(
            agent=agent,
            store=store,
            mailbox=mailbox,
            now=now,
            metrics=self.metrics,
            spans=spans,
        )
        self.runner = StepRunner(
            agent=agent,
            store=store,
            reader=ReadOnlyMailbox(mailbox),
            gateway=gateway,
            effects=self.executor,
            now=now,
            metrics=self.metrics,
            spans=spans,
        )
        self.tick = Tick(
            agent=agent,
            executor=self.executor,
            store=store,
            now=now,
            context=self.context,
        )
        self._gateway = gateway
        self._away = 0
        self._waiting: set[MessageRef] = set()
        # The message at which passes ended with the mailbox service away,
        # how many in a row, and whether this pass ended at one.
        self._stuck: MessageRef | None = None
        self._stuck_passes = 0
        self._ended_at_message = False

    @property
    def away(self) -> bool:
        """Whether the last pass found the mailbox service or the gateway
        away."""
        return self._away > 0

    @property
    def accounts(self) -> list[str] | None:
        return self.settings.accounts or None

    def context(self) -> Context:
        """A context without the model, for observe and tick."""
        calls = make_calls(
            self.agent,
            gateway=self._gateway,
            store=self.store,
            ref=MessageRef(account_id="", message_id=""),
            now=self._now,
            limits=Limits(model_calls_per_message=0, model_calls_per_day=0),
            metrics=self.metrics,
        )
        return self.runner.context(calls)

    # -- one pass ---------------------------------------------------------------

    async def run_pass(self) -> float:
        """One pass. Answers the seconds to wait before the next.

        It asks the service for its version first, in every pass: a
        service can be replaced by another release between two passes
        without one request failing."""
        started = time.monotonic()
        self._ended_at_message = False
        try:
            return await self._pass(started)
        finally:
            # A pass that ends otherwise starts the count again.
            if not self._ended_at_message:
                self._stuck, self._stuck_passes = None, 0

    async def _pass(self, started: float) -> float:
        await self._mailbox.ensure_matching()
        # The folders as they are now, once per pass: the owner may have
        # renamed one since the last.
        self._mailbox.forget_folders()
        state, events = await self._read_feed()
        observe = self._record(events)
        for ref in observe:
            await self._observe(ref)
            # A long feed of updates is progress: the health check must
            # not see a loop that stands while it works them.
            self.store.set_progress(self._now())
        away: UnavailableError | None = None
        try:
            await self.process_due()
            if self.runner.gateway_away is None or self._only_gateway_waits():
                await self.tick()
        except UnavailableError as exc:
            away = exc
        if away is None:
            away = self.runner.gateway_away
        now = self._now()
        self.store.set_cursor(state, now)
        self.store.set_progress(now)
        self._purge(now)
        self.metrics.state(self.store, now)
        record(
            worker.PassDone(
                agent=self.agent.label,
                seconds=time.monotonic() - started,
                pending=self.store.counts()["pending"],
            )
        )
        if away is not None:
            return self._wait_after(away)
        self._away = 0
        return self.settings.poll_seconds

    async def _read_feed(self) -> tuple[str, list[Event]]:
        state = self.store.cursor()
        if state is None:
            return await self._mailbox.start(self.accounts), []
        try:
            events, fresh = await self._mailbox.changes(state, self.accounts)
        except ChangesExpiredError:
            record(feed.Expired(agent=self.agent.label))
            fresh = await self._mailbox.start(self.accounts)
            await self._backfill(self.settings.backfill_days)
            # The backfill takes up new messages only. An update in the gap
            # of a message the agent follows is seen by observing it now.
            for item in self.store.open_items():
                await self._observe(item.ref)
            return fresh, []
        return fresh, events

    def _record(self, events: list[Event]) -> list[MessageRef]:
        """Record what the agent decides on, answer what it observes, each
        message once in the order of the feed."""
        now = self._now()
        # A dict keeps the order and finds a message in constant time.
        observe: dict[MessageRef, None] = {}
        selected = 0
        for event in events:
            route = self._route(event)
            if route is Route.DECIDE:
                self.store.enqueue(event.ref, now)
                selected += 1
            elif route is Route.OBSERVE and event.ref not in observe:
                observe[event.ref] = None
                selected += 1
        record(
            feed.Read(agent=self.agent.label, changes=len(events), selected=selected)
        )
        return list(observe)

    def _route(self, event: Event) -> Route | None:
        """Where the agent wants ``event``: None for a type it does not
        listen to, else what its ``select`` answers."""
        if event.type not in self.agent.triggers.events:
            return None
        return self.agent.select(event)

    async def _observe(self, ref: MessageRef) -> None:
        """Hand an updated message to the agent and take its actions. A
        message refused, before or in the middle of its actions, is logged
        and left. One gone closes its open item as ``message_gone``: no
        update of it can come any more."""
        try:
            message = await self._mailbox.message(ref)
            await self.executor(await self.agent.observe(message, self.context()))
            self._look_again(message)
            if self.agent.decide_again(message):
                self.store.enqueue(message.ref, self._now(), again=True)
        except (MailboxUnavailableError, MailboxRefusedError) as exc:
            # A service away is waited for, unless the message is stuck:
            # then its update is left, as a refused one is.
            if isinstance(exc, MailboxUnavailableError) and not self._stuck_at(ref):
                raise
            self.runner.failed(ref, "observe", exc)
            if isinstance(exc, MessageGoneError):
                self.store.close_item(ref, MESSAGE_GONE, self._now())

    def _look_again(self, message: MailMessage) -> None:
        """Take up again a message skipped as marked before the state file,
        once an update shows it without the agent's keyword: the owner took
        it off to have the message looked at again (decided 2026-11-19).
        Only for an agent that declares ``skip_marked``, and only a message
        with no step stored that the agent admits now."""
        agent = self.agent
        if not agent.skip_marked or message.has_keyword(agent.keyword):
            return
        row = self.store.message(message.ref)
        if row is None or row.state != "skipped" or self.store.steps(message.ref):
            return
        if agent.admit(message):
            self.store.enqueue(message.ref, self._now(), again=True)

    async def process_due(self) -> int:
        """Run the steps of the pending messages that are due. Answers how
        many were taken up.

        A gateway that is away leaves each message that needs it pending,
        no attempt counted, and is not asked again in this pass, while the
        messages that need no model go on."""
        self.runner.gateway_away = None
        self._waiting = set()
        rows = self.store.due(self._now(), BATCH)
        for row in rows:
            try:
                await self.runner.process(row.ref, row.attempts)
            except GatewayUnavailableError as exc:
                self.runner.gateway_away = exc
                self._waiting.add(row.ref)
            except MailboxUnavailableError as exc:
                if not self._stuck_at(row.ref):
                    raise
                self.runner.retry(row.ref, row.attempts)
                self.runner.failed(row.ref, "fetch", exc)
            self.store.set_progress(self._now())
        return len(rows)

    def _stuck_at(self, ref: MessageRef) -> bool:
        """Count a pass that the mailbox service, away, ended at ``ref``.
        Answers whether that happened ``max_attempts`` times in a row: then
        the message counts an attempt or its update is left, and the pass
        goes on. Each pass asked the service for its version first, so the
        service answered, only not for this message (decided 2026-11-20)."""
        if ref == self._stuck:
            self._stuck_passes += 1
        else:
            self._stuck, self._stuck_passes = ref, 1
        if self._stuck_passes >= self.settings.max_attempts:
            self._stuck, self._stuck_passes = None, 0
            return True
        self._ended_at_message = True
        return False

    async def drain(self) -> int:
        """Run the steps of the pending messages until none is due, as
        ``backfill`` and the live checks want. Answers how many were taken
        up. A gateway that is away is raised after the round that found it
        away: a message that needs it stays due with no attempt counted,
        so another round would ask it again and never end."""
        taken = 0
        while found := await self.process_due():
            taken += found
            if self.runner.gateway_away is not None:
                raise self.runner.gateway_away
        return taken

    def _only_gateway_waits(self) -> bool:
        """Whether every message still due waits for the gateway alone. Only
        then may the tick run without it: a reply still in the queue must
        close its item before a deadline marks it."""
        due = self.store.due(self._now(), len(self._waiting) + 1)
        return {row.ref for row in due} <= self._waiting

    def _purge(self, now: datetime) -> None:
        days = self.settings.prompt_retention_days
        self.store.purge_calls(now - timedelta(days=days))

    def _wait_after(self, error: UnavailableError) -> float:
        """The wait after an upstream that is away, logged as such."""
        wait = self._back_off(error)
        record(worker.UpstreamAway(agent=self.agent.label, error=error, wait=wait))
        return wait

    def _back_off(self, error: MailboxAgentError) -> float:
        """Count a failed pass and answer how long to wait before the
        next, longer each time in a row."""
        self._away += 1
        self.metrics.step_failed(error.code)
        return backoff(self.settings, self._away)

    # -- backfill ---------------------------------------------------------------

    async def backfill(self, days: int, *, again: bool = False) -> int:
        """Record the messages of the last ``days`` days the agent selects,
        as if each had just been created. With ``again`` a message decided
        before is taken up anew, for a new prompt or model. Answers how
        many are pending because of it. The service is asked for its
        version first, as a pass does."""
        await self._mailbox.ensure_matching()
        return await self._backfill(days, again=again)

    async def _backfill(self, days: int, *, again: bool = False) -> int:
        since = (self._now() - timedelta(days=days)).date()
        now = self._now()
        added = 0
        refs = await self._mailbox.recent(since, self.accounts, roles=BACKFILL_ROLES)
        refs += await self._in_folders(since)
        for ref in dict.fromkeys(refs):
            route = self._route(Event(type="message.created", ref=ref, at=now))
            if route is Route.DECIDE or (
                route is Route.OBSERVE and await self._waited_for(ref)
            ):
                added += self.store.enqueue(ref, now, again=again)
        record(feed.Backfilled(agent=self.agent.label, messages=added, days=days))
        return added

    async def _waited_for(self, ref: MessageRef) -> bool:
        """Whether a message the agent only observes when it arrives is to
        be decided now, as an update would have it: one that carries a
        keyword it waits for already. One gone is not."""
        try:
            message = await self._mailbox.message(ref)
        except MessageGoneError:
            return False
        return self.agent.decide_again(message)

    async def _in_folders(self, since: date) -> list[MessageRef]:
        """The messages of the folders the agent wants in a backfill besides
        those of :data:`BACKFILL_ROLES`, read already, in each account it
        works on: those the settings name, or else every account the user
        is granted, so one whose inbox and sent mail are empty is looked in
        too."""
        accounts = await accounts_of(self.settings, self._mailbox)
        refs: list[MessageRef] = []
        for account in accounts:
            folders = await self._mailbox.folders(account)
            for folder in folders.values():
                if folder.role in BACKFILL_ROLES:
                    continue
                if self.agent.backfill_folder(folder):
                    refs += await self._mailbox.recent_in(account, folder.id, since)
        return refs

    # -- the loop ---------------------------------------------------------------

    async def run(self, stop: asyncio.Event) -> None:
        """Pass after pass until ``stop`` is set."""
        while not stop.is_set():
            try:
                wait = await self.run_pass()
            except UnavailableError as exc:
                wait = self._wait_after(exc)
            except (StateFileError, ServiceVersionError):
                # Nothing goes on without the state file, nor against a
                # service of another version: a pass after it would
                # fail the same way, forever.
                raise
            except MailboxAgentError as exc:
                wait = self._back_off(exc)
                record(worker.PassFailed(agent=self.agent.label, error=exc, wait=wait))
            await self._sleep(wait, stop)

    async def _sleep(self, wait: float, stop: asyncio.Event) -> None:
        """Wait ``wait`` seconds or until ``stop``, in slices of at most one
        poll interval, writing progress after each. A loop that waits long
        for its gateway is alive, and the health check must see it so."""
        left = wait
        while left > 0 and not stop.is_set():
            step = min(left, self.settings.poll_seconds)
            try:
                await asyncio.wait_for(stop.wait(), timeout=step)
            except TimeoutError:
                self.store.set_progress(self._now())
            left -= step
