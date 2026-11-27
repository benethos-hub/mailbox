"""The step runner: one pending message through fetch, baseline, model,
check and effect.

Each step writes its result before the next begins. The baseline is stored
once per agent version and prompt version, the decision once per prompt
version and model alias, so a message run again, after a crash or a
repeated feed entry, reuses what was decided and asks the model nothing.
See docs/mailbox-agents/concept/runtime.md.
"""

from __future__ import annotations

import time
from collections.abc import Awaitable, Callable
from datetime import datetime, timedelta
from typing import TypeVar

from pydantic import BaseModel

from benethos_mailbox_common.values import pauses

from ..contract import ActionRequest, Agent, Context, Items, Limits, Reader
from ..errors import (
    AnswerRefusedError,
    GatewayUnavailableError,
    LimitReachedError,
    MailboxAgentError,
    MailboxRefusedError,
    MessageGoneError,
    UnavailableError,
)
from ..llm.evidence import check
from ..llm.gateway import Reply
from ..logbook import messages, record
from ..records import Decision, MailMessage, MessageRef, StepResult
from ..settings import Settings
from ..store import State, Store
from ..telemetry import NO_SPANS, Spans
from .items import StoredItems
from .metrics import Metrics
from .model import Asker, Calls, start_of_day

__all__ = [
    "Effects",
    "StepRunner",
    "backoff",
    "decide_checked",
    "make_calls",
    "make_context",
]

T = TypeVar("T", bound=BaseModel)

# What carries out the actions of an effect: the action executor.
Effects = Callable[[list[ActionRequest]], Awaitable[object]]


def backoff(settings: Settings, attempts: int) -> float:
    """Seconds to wait after ``attempts`` failed tries: twice as long each
    time, from the poll interval up to the ceiling."""
    return pauses.doubled(
        settings.poll_seconds, attempts, settings.backoff_ceiling_seconds
    )


def make_calls(
    agent: Agent,
    *,
    gateway: Asker,
    store: Store,
    ref: MessageRef,
    now: Callable[[], datetime],
    retention_days: int = 0,
    limits: Limits | None = None,
    metrics: Metrics | None = None,
) -> Calls:
    """The model calls of one attempt at one message, counted against the
    agent's limits unless others are named."""
    return Calls(
        gateway=gateway,
        store=store,
        ref=ref,
        limits=limits or agent.limits,
        prompt_version=agent.prompt_version,
        retention_days=retention_days,
        now=now,
        metrics=metrics,
    )


def make_context(
    *,
    calls: Calls,
    reader: Reader,
    store: Store,
    now: Callable[[], datetime],
    items: Items | None = None,
) -> Context:
    """The context an agent is handed, its open items over ``store``
    unless others are named."""
    return Context(
        model=calls,
        reader=reader,
        items=items or StoredItems(store, now),
        now=now,
    )


async def decide_checked(
    agent: Agent, message: MailMessage, context: Context, calls: Calls
) -> Decision:
    """The agent's decision, its evidence checked when the model made it:
    the same in operation and in the evaluation."""
    decided = await agent.decide(message, context)
    if decided.source == "model":
        decided = check(decided, calls.evidence)
    return decided


class _Away:
    """A gateway known to be away for the rest of a pass: every call fails
    at once, without a request."""

    def __init__(self, gateway: Asker, error: GatewayUnavailableError) -> None:
        self.model = gateway.model
        self._error = error

    async def ask(self, *, system: str, content: str, schema: type[T]) -> Reply[T]:
        raise self._error


class StepRunner:
    """Runs the steps of one agent's pending messages."""

    def __init__(
        self,
        *,
        agent: Agent,
        store: Store,
        reader: Reader,
        gateway: Asker,
        effects: Effects,
        now: Callable[[], datetime],
        metrics: Metrics | None = None,
        spans: Spans = NO_SPANS,
    ) -> None:
        self.metrics = metrics or Metrics(
            agent.name, agent.version, agent.settings.stage, agent.instance or ""
        )
        self.spans = spans
        self.agent = agent
        self.settings = agent.settings
        self._store = store
        self._reader = reader
        self._gateway = gateway
        self._effects = effects
        self._now = now
        self.items = StoredItems(store, now, agent.settings.stage)
        # Set by the loop when the gateway was found away in this pass.
        self.gateway_away: GatewayUnavailableError | None = None
        # The messages whose effect an upstream away cut off: a move may
        # have taken one out of what admit lets in, so it goes on to its
        # effect when it is run again.
        self._cut_off: set[MessageRef] = set()

    @property
    def model_alias(self) -> str:
        return self._gateway.model

    def calls(self, ref: MessageRef) -> Calls:
        gateway: Asker = self._gateway
        if self.gateway_away is not None:
            gateway = _Away(gateway, self.gateway_away)
        return make_calls(
            self.agent,
            gateway=gateway,
            store=self._store,
            ref=ref,
            now=self._now,
            retention_days=self.settings.prompt_retention_days,
            metrics=self.metrics,
        )

    def context(self, calls: Calls) -> Context:
        return make_context(
            calls=calls,
            reader=self._reader,
            store=self._store,
            now=self._now,
            items=self.items,
        )

    def _state(
        self,
        ref: MessageRef,
        state: State,
        *,
        attempts: int | None = None,
        next_attempt: datetime | None = None,
    ) -> State:
        self._store.set_state(
            ref, state, self._now(), attempts=attempts, next_attempt=next_attempt
        )
        record(
            messages.StateSet(
                agent=self.agent.label, message_id=ref.message_id, state=state
            )
        )
        return state

    def failed(self, ref: MessageRef, step: str, exc: MailboxAgentError) -> None:
        """The line and the count of a step that failed."""
        record(
            messages.StepFailed(
                agent=self.agent.label, message_id=ref.message_id, step=step, error=exc
            )
        )
        self.metrics.step_failed(exc.code)

    def retry(self, ref: MessageRef, attempts: int) -> str:
        """Count an attempt: the message waits by the backoff, or fails
        once it has had as many as it may."""
        tried = attempts + 1
        if tried >= self.settings.max_attempts:
            return self._state(ref, "failed", attempts=tried)
        wait = timedelta(seconds=backoff(self.settings, tried))
        return self._state(
            ref, "pending", attempts=tried, next_attempt=self._now() + wait
        )

    async def process(self, ref: MessageRef, attempts: int = 0) -> str:
        """Run the steps of one message. Answers the state it is left in.

        A mailbox service or a gateway that is away, and a configuration
        error, are raised to the loop and leave the message as it was. The
        steps run in a span of the message, with the state it is left in.
        """
        with self.spans.span(
            "message",
            agent=self.agent.label,
            account_id=ref.account_id,
            message_id=ref.message_id,
            attempt=attempts + 1,
        ) as span:
            state = await self._process(ref, attempts)
            span.set("state", state)
            return state

    async def _process(self, ref: MessageRef, attempts: int) -> str:
        try:
            message = await self._reader.message(ref)
        except MailboxRefusedError as exc:
            return self._refused(ref, attempts, exc, "fetch")
        if ref not in self._cut_off and (
            not self.agent.admit(message) or self._marked_before(message)
        ):
            return self._state(ref, "skipped")
        self._baseline(message)
        calls = self.calls(ref)
        try:
            decision = await self._decision(message, calls)
        except AnswerRefusedError as exc:
            record(
                messages.AnswerRefused(
                    agent=self.agent.label,
                    message_id=ref.message_id,
                    reason=exc.reason,
                )
            )
            return self.retry(ref, attempts)
        except LimitReachedError as exc:
            self.failed(ref, "model", exc)
            if not exc.per_day:
                return self._state(ref, "failed", attempts=attempts + 1)
            tomorrow = start_of_day(self._now()) + timedelta(days=1)
            return self._state(ref, "pending", next_attempt=tomorrow)
        except MailboxRefusedError as exc:
            self.failed(ref, "decide", exc)
            return self.retry(ref, attempts)
        if not decision.actionable:
            self.metrics.answer_refused(decision.refused or "")
            return self._state(ref, "decided")
        if calls.count:
            # The model takes its time, and another agent or a person may
            # move the message meanwhile: the agent acts on where it lies
            # now, not where it lay when it was read.
            try:
                message = await self._reader.message(ref)
            except MailboxRefusedError as exc:
                return self._refused(ref, attempts, exc, "fetch")
        return await self._act(decision, message, calls, attempts)

    def _marked_before(self, message: MailMessage) -> bool:
        """Whether the agent skips marked mail and the message carries its
        keyword with no step of it in the state file: marked before this
        state file. One it ran a step for, as ``backfill`` takes up again
        after a change of stage or prompt, goes on."""
        return (
            self.agent.skip_marked
            and message.has_keyword(self.agent.keyword)
            and not self._store.steps(message.ref)
        )

    def _refused(
        self, ref: MessageRef, attempts: int, exc: MailboxRefusedError, step: str
    ) -> str:
        """A message the service refused in ``step``, to hand over or for
        what the agent read for its actions: skipped when it is gone, else
        an attempt counted. Either way the message is asked ``admit`` again
        when it comes back."""
        self._cut_off.discard(ref)
        self.failed(ref, step, exc)
        if isinstance(exc, MessageGoneError):
            return self._state(ref, "skipped")
        return self.retry(ref, attempts)

    async def _act(
        self, decision: Decision, message: MailMessage, calls: Calls, attempts: int
    ) -> str:
        """Ask the agent what to do and have it done. A refusal of what the
        agent read for it, such as an earlier message of the thread deleted
        since, ends the message as skipped when it is gone, and counts as
        an attempt otherwise."""
        ref = message.ref
        try:
            requests = await self.agent.effect(decision, message, self.context(calls))
            await self._effects(requests)
        except UnavailableError:
            # Some of its actions may be taken: the effect is asked again,
            # and finds what is done there already.
            self._cut_off.add(ref)
            raise
        except MailboxRefusedError as exc:
            return self._refused(ref, attempts, exc, "effect")
        self._cut_off.discard(ref)
        return self._state(ref, "done")

    def _baseline_version(self) -> str:
        """What the baseline is stored under: the agent version, and the
        prompt version beside it when there is one. For ``categorization`` the
        prompt version is the list, which its rules read as well, so a
        changed list runs the rules anew beside the new decision."""
        if not self.agent.prompt_version:
            return self.agent.version
        return f"{self.agent.version}/{self.agent.prompt_version}"

    def _baseline(self, message: MailMessage) -> None:
        ref = message.ref
        version = self._baseline_version()
        if self._store.step(ref, "baseline", version, "") is not None:
            return
        started = time.monotonic()
        decided = self.agent.baseline(message)
        self._store.add_step(
            ref,
            StepResult(
                step="baseline",
                prompt_version=version,
                result=decided.model_dump(mode="json"),
                duration_ms=_since(started),
                at=self._now(),
            ),
            "",
        )

    async def _decision(self, message: MailMessage, calls: Calls) -> Decision:
        """The decision of the model with its evidence checked, stored once
        per prompt version and model alias, in a span with a span below it
        for each part the agent names."""
        with self.spans.span("decision", agent=self.agent.label) as span:
            decided = await self._decided(message, calls)
            span.set("source", decided.source)
            span.set("model_calls", calls.count)
            span.set("refused", decided.refused or "")
            for part in self.agent.trace_parts(decided):
                with self.spans.span(part.name, **dict(part.attributes)):
                    pass
            return decided

    async def _decided(self, message: MailMessage, calls: Calls) -> Decision:
        ref = message.ref
        stored = self._store.step(
            ref, "decision", self.agent.prompt_version, self.model_alias
        )
        if stored is not None:
            return self.agent.refresh(Decision.model_validate(stored.result), message)
        started = time.monotonic()
        decided = await decide_checked(self.agent, message, self.context(calls), calls)
        for item in decided.evidence:
            if item.found is False:
                record(
                    messages.QuoteMissing(
                        agent=self.agent.label,
                        message_id=ref.message_id,
                        field=item.field,
                    )
                )
        duration = _since(started)
        self._store.add_step(
            ref,
            StepResult(
                step="decision",
                prompt_version=self.agent.prompt_version,
                model=",".join(dict.fromkeys(calls.models)),
                result=decided.model_dump(mode="json"),
                tokens_in=calls.tokens_in,
                tokens_out=calls.tokens_out,
                duration_ms=duration,
                at=self._now(),
            ),
            self.model_alias,
        )
        record(
            messages.StepDone(
                agent=self.agent.label,
                message_id=ref.message_id,
                step="decision",
                ms=duration,
            )
        )
        return decided


def _since(started: float) -> int:
    return int((time.monotonic() - started) * 1000)
