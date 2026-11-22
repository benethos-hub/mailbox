"""Metrics in the Prometheus text format, the only module that imports
prometheus_client.

Each process keeps a registry of its own, for its one agent: messages per
state, the age of the oldest pending message, step failures by kind,
answers refused by the schema, the gateway or the evidence check, model
calls with their tokens and duration, actions by kind and whether they
were carried out, and the time of the last pass. See
docs/mailbox-agents/concept/operation.md.
"""

from __future__ import annotations

from collections.abc import Iterator
from contextlib import contextmanager
from datetime import datetime

from prometheus_client import (
    CollectorRegistry,
    Counter,
    Gauge,
    Histogram,
    Info,
    generate_latest,
    start_http_server,
)

from ..errors import ConfigError
from ..store import Store

__all__ = ["Metrics"]

_PREFIX = "mailbox_agents"


class Metrics:
    """The metrics of one agent's process."""

    def __init__(self, agent: str, version: str, stage: str) -> None:
        self.registry = CollectorRegistry()
        r = self.registry
        Info(f"{_PREFIX}", "The agent of this process.", registry=r).info(
            {"agent": agent, "version": version, "stage": stage}
        )
        self.messages = Gauge(
            f"{_PREFIX}_messages", "Messages per state.", ["state"], registry=r
        )
        self.oldest_pending = Gauge(
            f"{_PREFIX}_oldest_pending_age_seconds",
            "Age of the oldest pending message, 0 when none is pending.",
            registry=r,
        )
        self.last_pass = Gauge(
            f"{_PREFIX}_last_pass_timestamp_seconds",
            "When the last pass of the loop finished.",
            registry=r,
        )
        self.step_failures = Counter(
            f"{_PREFIX}_step_failures",
            "Steps that failed, by kind.",
            ["kind"],
            registry=r,
        )
        self.refused = Counter(
            f"{_PREFIX}_answers_refused",
            "Model answers refused: schema, request or evidence.",
            ["reason"],
            registry=r,
        )
        self.model_calls = Counter(
            f"{_PREFIX}_model_calls", "Model calls answered.", registry=r
        )
        self.tokens = Counter(
            f"{_PREFIX}_model_tokens",
            "Tokens of model calls.",
            ["direction"],
            registry=r,
        )
        self.model_seconds = Histogram(
            f"{_PREFIX}_model_call_seconds",
            "Duration of a model call.",
            buckets=(0.5, 1, 2, 5, 10, 20, 30, 60, 120),
            registry=r,
        )
        self.actions = Counter(
            f"{_PREFIX}_actions",
            "Actions recorded, by action and whether they were carried out.",
            ["action", "executed"],
            registry=r,
        )

    # -- what the runtime reports ---------------------------------------------------

    def model_call(self, tokens_in: int, tokens_out: int, duration_ms: int) -> None:
        self.model_calls.inc()
        self.tokens.labels("in").inc(tokens_in)
        self.tokens.labels("out").inc(tokens_out)
        self.model_seconds.observe(duration_ms / 1000)

    def answer_refused(self, reason: str) -> None:
        self.refused.labels(reason).inc()

    def step_failed(self, kind: str) -> None:
        self.step_failures.labels(kind).inc()

    def action(self, action: str, executed: bool) -> None:
        self.actions.labels(action, "yes" if executed else "no").inc()

    def state(self, store: Store, now: datetime) -> None:
        """The gauges read from the state file after a pass."""
        for state, count in store.counts().items():
            self.messages.labels(state).set(count)
        oldest = store.oldest_pending()
        self.oldest_pending.set((now - oldest).total_seconds() if oldest else 0)
        last = store.progress()
        if last is not None:
            self.last_pass.set(last.timestamp())

    # -- serving -------------------------------------------------------------------

    def text(self) -> bytes:
        return generate_latest(self.registry)

    @contextmanager
    def serving(self, port: int, addr: str = "0.0.0.0") -> Iterator[None]:
        """Serve the metrics on ``port`` in a thread of their own while the
        block runs, and stop serving after it. A port taken by another
        process, or one this process may not bind, is a
        :class:`ConfigError` naming the setting."""
        try:
            server, thread = start_http_server(port, addr=addr, registry=self.registry)
        except OSError as exc:
            raise ConfigError(
                f"the metrics cannot be served on port {port} "
                f"({type(exc).__name__}): choose another "
                "MAILBOX_AGENTS_METRICS_PORT"
            ) from None
        try:
            yield
        finally:
            server.shutdown()
            server.server_close()
            thread.join()
