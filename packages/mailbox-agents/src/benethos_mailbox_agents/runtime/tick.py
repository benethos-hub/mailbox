"""The tick of a worker: what is due without an event.

At most once every ``tick_seconds`` the agent is asked what is due, such
as a deadline of an open item. Each message's actions go through the
executor at once, and what became of a keyword is kept on its open item.
See docs/mailbox-agents/concept/runtime.md.
"""

from __future__ import annotations

from collections.abc import Callable
from datetime import datetime, timedelta

from ..contract import Action, ActionRequest, Agent, Context
from ..errors import MessageGoneError
from ..logbook import record, worker
from ..records import MESSAGE_DISCARDED, MESSAGE_GONE, MessageRef
from ..store import Store
from .actions import Executor, Outcome

__all__ = ["Tick"]


class Tick:
    """The tick of one agent over its state file."""

    def __init__(
        self,
        *,
        agent: Agent,
        executor: Executor,
        store: Store,
        now: Callable[[], datetime],
        context: Callable[[], Context],
    ) -> None:
        self.agent = agent
        self.settings = agent.settings
        self.executor = executor
        self.store = store
        self._now = now
        self._context = context
        self._last: datetime | None = None

    async def __call__(self) -> None:
        if not self.agent.triggers.tick:
            return
        now = self._now()
        if self._last is not None and now - self._last < timedelta(
            seconds=self.settings.tick_seconds
        ):
            return
        requests: list[ActionRequest] = await self.agent.tick(now, self._context())
        # Each message's actions through the executor at once, so a refused
        # move stops what was asked after it for that message.
        by_message: dict[MessageRef, list[ActionRequest]] = {}
        for request in requests:
            by_message.setdefault(request.ref, []).append(request)
        for ref, group in by_message.items():
            try:
                outcomes = await self.executor(group)
            except MessageGoneError:
                # No tick could set its keyword again, nor take it off: an
                # item closed already keeps its reason, and its keyword
                # counts as gone with the message.
                self.store.close_item(ref, MESSAGE_GONE, self._now())
                self.store.mark_keyword(ref, False)
                continue
            for request, outcome in zip(group, outcomes, strict=False):
                self._note(request, outcome)
        self._last = now
        record(worker.TickDone(agent=self.agent.label, actions=len(requests)))

    def _note(self, request: ActionRequest, outcome: Outcome) -> None:
        """Keep on an open item what became of its keyword: set when it is on
        the message, recorded in this stage when the stage did not allow it.
        A refused keyword leaves the item due. An item whose message is not
        there any more is closed by the tick as ``message_gone``. A message
        in the trash, junk or spam is not asked again: a keyword to take off
        counts as gone, and an item due there closes as ``discarded``."""
        if request.action is Action.REMOVE_KEYWORD:
            if outcome in (Outcome.DONE, Outcome.PRESENT, Outcome.DISCARDED):
                self.store.mark_keyword(request.ref, False)
            return
        if request.action is not Action.ADD_KEYWORD:
            return
        if outcome in (Outcome.DONE, Outcome.PRESENT):
            self.store.mark_keyword(request.ref, True)
        elif outcome is Outcome.RECORDED:
            self.store.record_keyword_stage(request.ref, self.settings.stage)
        elif outcome is Outcome.DISCARDED:
            self.store.close_item(request.ref, MESSAGE_DISCARDED, self._now())
