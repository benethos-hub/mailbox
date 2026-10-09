"""The state of the service: the sync worker, and how each account the
caller may see the status of fares. Nothing is asked of a provider."""

from __future__ import annotations

from dataclasses import dataclass
from datetime import datetime


@dataclass(frozen=True)
class Worker:
    """The sync worker: every ``interval`` seconds, with ``push`` where a
    server offers it, ``watching`` accounts of at most ``watchers``."""

    interval: float
    push: bool
    last_pass_at: datetime | None
    watchers: int
    watching: int


@dataclass(frozen=True)
class AccountHealth:
    """How an account fares: ``synced`` whether a pass does anything for
    it, ``watching`` whether a watcher waits for its server, ``attention``
    whether a person should look at it."""

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


@dataclass(frozen=True)
class Status:
    """The worker, None when it is switched off, and the accounts."""

    worker: Worker | None
    accounts: tuple[AccountHealth, ...]
