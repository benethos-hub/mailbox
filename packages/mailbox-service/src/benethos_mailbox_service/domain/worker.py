"""The background worker: keeps the id mapping current (CONCEPT 8.1).

Every ``interval`` seconds it syncs each account whose ids are mapped. Where
the provider can push, a watcher per account waits for the server to report
a change in the inbox (IMAP IDLE) and syncs at once. Accounts whose login
was rejected are left alone until they are verified.
"""

from __future__ import annotations

import logging
from collections.abc import Awaitable, Callable
from dataclasses import dataclass
from datetime import datetime

import anyio
from anyio.abc import TaskGroup

from ..common.clock import utc_now
from ..data.models import AccountStatus
from ..data.providers import Capability, backoff
from ..errors import (
    MailboxServiceError,
    NotFoundError,
    NotSupportedError,
    ProviderAuthError,
)
from .adapters import Adapters
from .sync import SyncService

# RFC 2177: IDLE is to be renewed before 29 minutes.
IDLE_RENEW = 25 * 60.0
# A watcher that failed waits, doubling up to the longest pause, with
# jitter so that many accounts do not retry in step.
FIRST_RETRY = 60.0
LONGEST_RETRY = 900.0

# How the background loops wait. Tests pass one that returns at once.
Sleep = Callable[[float], Awaitable[None]]

log = logging.getLogger(__name__)


@dataclass(frozen=True)
class WorkerState:
    """What the worker does, for the status page. In memory only."""

    interval: float
    push: bool
    # When the last round over every account ended. None before the first.
    last_pass_at: datetime | None
    # Accounts a watcher waits on for the server to report a change.
    watching: frozenset[str]


class SyncWorker:
    def __init__(
        self,
        adapters: Adapters,
        sync: SyncService,
        *,
        interval: float,
        push: bool = True,
        sleep: Sleep = anyio.sleep,
        clock: Callable[[], datetime] = utc_now,
    ) -> None:
        self._adapters = adapters
        self._sync = sync
        self._interval = interval
        self._push = push
        self._sleep = sleep
        self._clock = clock
        self._watching: set[str] = set()
        self._no_push: set[str] = set()
        self._last_pass_at: datetime | None = None

    def state(self) -> WorkerState:
        return WorkerState(
            interval=self._interval,
            push=self._push,
            last_pass_at=self._last_pass_at,
            watching=frozenset(self._watching),
        )

    async def run(self) -> None:
        """Until cancelled. A failure ends a round, never the worker."""
        async with anyio.create_task_group() as watchers:
            while True:
                try:
                    await self.poll(watchers)
                except Exception:
                    log.exception("a sync round failed")
                await self._sleep(self._interval)

    async def poll(self, watchers: TaskGroup | None = None) -> None:
        """One round over every account, one after the other."""
        for account_id in self._adapters.ids():
            try:
                if not self._wanted(account_id):
                    continue
                if watchers is not None and self._push_for(account_id):
                    self._watching.add(account_id)
                    watchers.start_soon(self.watch, account_id)
                await self._sync.sync_account(account_id)
            except NotFoundError:
                continue  # deleted meanwhile
            except MailboxServiceError as exc:
                log.warning("sync of %s failed: %s", account_id, exc.message)
            except Exception:
                # A bug in one adapter must not stop the sync of the others.
                log.exception("sync of %s failed", account_id)
        self._last_pass_at = self._clock()

    async def watch(self, account_id: str) -> None:
        """Wait for changes the server reports, and sync on each."""
        failures = 0
        try:
            while self._wanted(account_id):
                try:
                    changed = await self._adapters.call(
                        account_id, lambda p: p.wait_for_change(IDLE_RENEW)
                    )
                    failures = 0
                    if changed:
                        await self._sync.sync_account(account_id)
                except NotSupportedError:
                    self._no_push.add(account_id)
                    log.info("%s cannot push changes: polling only", account_id)
                    return
                except ProviderAuthError:
                    return  # _wanted is false now, until the account is verified
                except NotFoundError:
                    return  # deleted meanwhile
                except Exception as exc:
                    failures += 1
                    pause = backoff(failures - 1, FIRST_RETRY, LONGEST_RETRY)
                    log.warning(
                        "watching %s failed, next try in %.0fs: %s",
                        account_id,
                        pause,
                        _reason(exc),
                        exc_info=not isinstance(exc, MailboxServiceError),
                    )
                    await self._sleep(pause)
        except NotFoundError:
            return  # deleted
        finally:
            self._watching.discard(account_id)

    def _wanted(self, account_id: str) -> bool:
        return self._adapters.status(
            account_id
        ) is not AccountStatus.NEEDS_REAUTH and self._sync.watched(account_id)

    def _push_for(self, account_id: str) -> bool:
        return (
            self._push
            and account_id not in self._watching
            and account_id not in self._no_push
            and Capability.PUSH in self._adapters.capabilities(account_id)
        )


def _reason(exc: Exception) -> str:
    """The message of one of our errors, else the kind of the failure."""
    if isinstance(exc, MailboxServiceError):
        return exc.message
    return type(exc).__name__
