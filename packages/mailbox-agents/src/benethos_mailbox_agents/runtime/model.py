"""The model as an agent reaches it: one message's calls, counted and kept.

:class:`Calls` is the :class:`~benethos_mailbox_agents.contract.Model` the
runtime hands an agent for one message. It refuses a call past the agent's
limits, records each call as a step ``model`` with the model the gateway
reported, its tokens and its duration, keeps the parts of the mail it sent
for the evidence check, and keeps request and answer only while
PROMPT_RETENTION_DAYS says so.
"""

from __future__ import annotations

from collections.abc import Callable, Sequence
from datetime import datetime
from typing import Protocol, TypeVar

from pydantic import BaseModel

from ..contract import Limits
from ..errors import AnswerRefusedError, ConfigError, LimitReachedError
from ..llm.gateway import Reply
from ..records import MessageRef, StepResult
from ..store import Store
from .metrics import Metrics

__all__ = ["Asker", "Calls", "NoModel", "start_of_day"]

T = TypeVar("T", bound=BaseModel)


class Asker(Protocol):
    """What :class:`Calls` needs of the gateway: one call with a schema."""

    model: str

    async def ask(self, *, system: str, content: str, schema: type[T]) -> Reply[T]:
        """One call of the model, its answer in ``schema``."""


class NoModel:
    """The gateway of an agent that asks no model."""

    model = ""

    async def ask(self, *, system: str, content: str, schema: type[T]) -> Reply[T]:
        raise ConfigError("this agent asks no model")


def start_of_day(moment: datetime) -> datetime:
    return moment.replace(hour=0, minute=0, second=0, microsecond=0)


class Calls:
    """The model calls of one attempt at one message."""

    def __init__(
        self,
        *,
        gateway: Asker,
        store: Store,
        ref: MessageRef,
        limits: Limits,
        prompt_version: str,
        retention_days: int,
        now: Callable[[], datetime],
        metrics: Metrics | None = None,
    ) -> None:
        self._metrics = metrics or Metrics("", "", "")
        self._gateway = gateway
        self._store = store
        self._ref = ref
        self._limits = limits
        self._prompt_version = prompt_version
        self._retention_days = retention_days
        self._now = now
        self.parts: list[str] = []
        self.models: list[str] = []
        self.count = 0
        self.tokens_in = 0
        self.tokens_out = 0
        self.duration_ms = 0

    @property
    def evidence(self) -> tuple[str, ...]:
        """The parts of the mail the model was given, the frame left out:
        what the evidence check looks in."""
        return tuple(self.parts)

    async def ask(
        self,
        *,
        system: str,
        content: str,
        schema: type[T],
        evidence: Sequence[str],
    ) -> T:
        if self.count >= self._limits.model_calls_per_message:
            raise LimitReachedError(
                "the agent asked for more model calls per message than it may",
                per_day=False,
            )
        today = start_of_day(self._now())
        if self._store.model_calls_since(today) >= self._limits.model_calls_per_day:
            raise LimitReachedError(
                "the agent made its model calls for today", per_day=True
            )
        self.count += 1
        self.parts.extend(evidence)
        try:
            reply = await self._gateway.ask(
                system=system, content=content, schema=schema
            )
            longest = max(map(len, _texts(reply.value.model_dump())), default=0)
            if longest > self._limits.answer_text:
                raise AnswerRefusedError(
                    f"a text of the answer is longer than "
                    f"{self._limits.answer_text} characters",
                    reason="schema",
                )
        except AnswerRefusedError as exc:
            self._record({"refused": exc.reason}, "", 0, 0, 0)
            self._metrics.answer_refused(exc.reason)
            raise
        self.models.append(reply.model)
        self.tokens_in += reply.tokens_in
        self.tokens_out += reply.tokens_out
        self.duration_ms += reply.duration_ms
        # The step first: the daily limit counts stored steps.
        self._record(
            {"answer": reply.value.model_dump(mode="json")},
            reply.model,
            reply.tokens_in,
            reply.tokens_out,
            reply.duration_ms,
        )
        self._metrics.model_call(reply.tokens_in, reply.tokens_out, reply.duration_ms)
        if self._retention_days > 0:
            self._store.add_call(self._ref, reply.request, reply.answer, self._now())
        return reply.value

    def _record(
        self,
        result: dict[str, object],
        model: str,
        tokens_in: int,
        tokens_out: int,
        duration_ms: int,
    ) -> None:
        self._store.add_step(
            self._ref,
            StepResult(
                step="model",
                prompt_version=self._prompt_version,
                model=model,
                result=result,
                tokens_in=tokens_in,
                tokens_out=tokens_out,
                duration_ms=duration_ms,
                at=self._now(),
            ),
            self._gateway.model,
        )


def _texts(value: object) -> list[str]:
    """Every string in ``value``, nested ones among them."""
    if isinstance(value, str):
        return [value]
    if isinstance(value, dict):
        return [text for item in value.values() for text in _texts(item)]
    if isinstance(value, list):
        return [text for item in value for text in _texts(item)]
    return []
