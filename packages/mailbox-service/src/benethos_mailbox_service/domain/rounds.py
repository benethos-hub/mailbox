"""The background loops of the services: a round, then a pause, until the
service stops."""

from __future__ import annotations

from collections.abc import Awaitable, Callable
from typing import NoReturn

from ..errors import StorageUnavailableError
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
    cancelled. A failure ends its round and is recorded, never the loop.
    A database away is not recorded a round: the log says it once when
    it goes. The pause is then at least the seconds until the database
    is tried again."""
    while True:
        wait = pause
        try:
            await one()
        except StorageUnavailableError as exc:
            wait = max(pause, float(exc.retry_after))
        except Exception as exc:
            activity.record(system.RoundFailed(by=by, error=exc))
        await sleep(wait)
