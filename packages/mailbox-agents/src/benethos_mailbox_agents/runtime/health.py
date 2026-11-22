"""The health check: whether the loop of an agent still makes progress.

The loop writes the time of its last sign of progress into the state file:
after each message it ran and at the end of each pass. The check reads the
file beside the running agent and passes while that time is younger than
three poll intervals plus one model call. A process that is alive and stuck
fails it. A gateway that is away does not, since the loop goes on and waits.
See docs/mailbox-agents/concept/operation.md.
"""

from __future__ import annotations

from dataclasses import dataclass
from datetime import datetime, timedelta

from ..settings import Settings
from ..store import Store

__all__ = ["Health", "check", "window"]


def window(settings: Settings) -> timedelta:
    """How old the last sign of progress may be."""
    return timedelta(
        seconds=3 * settings.poll_seconds + settings.gateway_timeout_seconds
    )


@dataclass(frozen=True)
class Health:
    healthy: bool
    reason: str


def check(store: Store, settings: Settings, now: datetime) -> Health:
    last = store.progress()
    if last is None:
        return Health(False, "no progress yet")
    age = now - last
    return Health(
        age <= window(settings), f"last progress {int(age.total_seconds())}s ago"
    )
