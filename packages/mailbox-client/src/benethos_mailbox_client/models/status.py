"""The state of the service: the sync worker, and how each account the
caller may see the status of fares. Nothing is asked of a provider."""

from __future__ import annotations

from dataclasses import dataclass
from datetime import datetime


@dataclass(frozen=True, slots=True)
class Worker:
    """The sync worker: every ``interval`` seconds, with ``push`` where a
    server offers it, ``watching`` accounts of at most ``watchers``."""

    interval: float
    push: bool
    last_pass_at: datetime | None
    watchers: int
    watching: int


@dataclass(frozen=True, slots=True)
class AccountHealth:
    """How an account fares: ``synced`` whether a pass does anything for
    it, ``watching`` whether a watcher waits for its server, ``attention``
    whether a person should look at it. ``outbox_queued`` counts the sends
    waiting in its outbox, ``outbox_failed`` and ``outbox_unknown`` those
    of the last 24 hours that failed or whose outcome is unknown."""

    id: str
    email: str
    provider: str
    status: str
    synced: bool
    watching: bool
    last_sync_at: datetime | None
    last_error: str | None
    last_error_at: datetime | None
    attention: bool
    outbox_queued: int = 0
    outbox_failed: int = 0
    outbox_unknown: int = 0


@dataclass(frozen=True, slots=True)
class Status:
    """The worker, None when it is switched off, and the accounts."""

    worker: Worker | None
    accounts: tuple[AccountHealth, ...]
