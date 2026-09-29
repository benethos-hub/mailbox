"""Sync and the worker (docs/LOGGING.md 5.5)."""

from __future__ import annotations

import logging
from dataclasses import dataclass
from typing import ClassVar

from ....data.models import Account
from ..base import Activity, Failure, account, plural


@dataclass(frozen=True, kw_only=True)
class WorkerStarted(Activity):
    name: ClassVar[str] = "worker_started"

    interval: float
    push: bool

    def says(self) -> str:
        push = "and waits for pushed changes" if self.push else "without push"
        return f"started: it syncs every {self.interval:.0f}s {push}"


@dataclass(frozen=True, kw_only=True)
class Synced(Activity):
    """One pass of one account, with what it found."""

    name: ClassVar[str] = "synced"
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
    name: ClassVar[str] = "failed"

    account: Account

    def says(self) -> str:
        return f"could not sync {account(self.account)}"


@dataclass(frozen=True, kw_only=True)
class Watching(Activity):
    name: ClassVar[str] = "watching"

    account: Account

    def says(self) -> str:
        return f"watches {account(self.account)} for changes the server pushes"


@dataclass(frozen=True, kw_only=True)
class PushUnavailable(Activity):
    name: ClassVar[str] = "push_unavailable"

    account: Account

    def says(self) -> str:
        return f"found that {account(self.account)} cannot push changes: polling only"


@dataclass(frozen=True, kw_only=True)
class WatchPostponed(Activity):
    name: ClassVar[str] = "watch_postponed"

    account: Account
    watchers: int

    def says(self) -> str:
        return (
            f"polls {account(self.account)} only: all {self.watchers} "
            "watchers are in use"
        )


@dataclass(frozen=True, kw_only=True)
class IdleRenewed(Activity):
    name: ClassVar[str] = "idle_renewed"
    level: ClassVar[int] = logging.DEBUG

    account: Account

    def says(self) -> str:
        return f"renewed IDLE on {account(self.account)}"


@dataclass(frozen=True, kw_only=True)
class WatchFailed(Failure):
    name: ClassVar[str] = "watch_failed"

    account: Account
    pause: float

    def says(self) -> str:
        return f"could not watch {account(self.account)}, next try in {self.pause:.0f}s"
