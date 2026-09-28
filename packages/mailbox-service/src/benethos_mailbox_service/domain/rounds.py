"""The background loops of the services: a round, then a pause, until the
service stops."""

from __future__ import annotations

from collections.abc import Awaitable, Callable
from typing import NoReturn

from .activity import ActivityLog, Actor, system


async def rounds(
    one: Callable[[], Awaitable[None]],
    *,
    pause: float,
    sleep: Callable[[float], Awaitable[None]],
    activity: ActivityLog,
    by: Actor,
) -> NoReturn:
    """``one`` round after another, ``pause`` seconds apart, until
    cancelled. A failure ends its round and is recorded, never the loop."""
    while True:
        try:
            await one()
        except Exception as exc:
            activity.record(system.RoundFailed(by=by, error=exc))
        await sleep(pause)
