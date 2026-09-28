"""Sync and the worker (docs/LOGGING.md 5.5)."""

from __future__ import annotations

import logging
from dataclasses import dataclass
from datetime import datetime
from typing import ClassVar

from ....data.models import Account
from ..base import Activity, Failure, account, plural


@dataclass(frozen=True, kw_only=True)
class WorkerStarted(Activity):
    interval: float
    push: bool

    def says(self) -> str:
        push = "and waits for pushed changes" if self.push else "without push"
        return f"started: it syncs every {self.interval:.0f}s {push}"


@dataclass(frozen=True, kw_only=True)
class Synced(Activity):
    """One pass of one account, with what it found."""

    level: ClassVar[int] = logging.DEBUG

    account: Account
    folders: int
    created: int
    updated: int
    deleted: int

    def says(self) -> str:
        return (
            f"synced {account(self.account)}: {plural(self.folders, 'folder')}, "
            f"+{self.created} -{self.deleted} ~{self.updated}"
        )


@dataclass(frozen=True, kw_only=True)
class SyncFailed(Failure):
    account: Account

    def says(self) -> str:
        return f"could not sync {account(self.account)}"


@dataclass(frozen=True, kw_only=True)
class Watching(Activity):
    account: Account

    def says(self) -> str:
        return f"watches {account(self.account)} for changes the server pushes"


@dataclass(frozen=True, kw_only=True)
class PushUnavailable(Activity):
    account: Account

    def says(self) -> str:
        return f"found that {account(self.account)} cannot push changes: polling only"


@dataclass(frozen=True, kw_only=True)
class IdleRenewed(Activity):
    level: ClassVar[int] = logging.DEBUG

    account: Account

    def says(self) -> str:
        return f"renewed IDLE on {account(self.account)}"


@dataclass(frozen=True, kw_only=True)
class WatchFailed(Failure):
    account: Account
    pause: float

    def says(self) -> str:
        return f"could not watch {account(self.account)}, next try in {self.pause:.0f}s"


@dataclass(frozen=True, kw_only=True)
class ChangesPurged(Activity):
    """Changes older than the feed keeps are gone: a client or webhook
    that had not read them yet starts after them. The normal course, once
    an hour at most, so no warning."""

    count: int
    before: datetime

    def says(self) -> str:
        return (
            f"purged {plural(self.count, 'change')} older than "
            f"{self.before.isoformat(timespec='seconds')} from the change log"
        )
