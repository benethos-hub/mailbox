"""Sync and the worker (docs/LOGGING.md 5.5)."""

from __future__ import annotations

from dataclasses import dataclass

from ....data.models import Account
from ..base import Activity, Failure, account


@dataclass(frozen=True, kw_only=True)
class SyncFailed(Failure):
    account: Account

    def says(self) -> str:
        return f"could not sync {account(self.account)}"


@dataclass(frozen=True, kw_only=True)
class PushUnavailable(Activity):
    account: Account

    def says(self) -> str:
        return f"found that {account(self.account)} cannot push changes: polling only"


@dataclass(frozen=True, kw_only=True)
class WatchFailed(Failure):
    account: Account
    pause: float

    def says(self) -> str:
        return f"could not watch {account(self.account)}, next try in {self.pause:.0f}s"
