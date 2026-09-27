"""The state of the service, for the overview and the status page
(docs/UI.md, sections 5 and 6.5).

It reads what the other services keep: the accounts, the sync state of
each, the worker and the caller's webhooks. Nothing is asked of a
provider for it.
"""

from __future__ import annotations

from dataclasses import dataclass

from ..data.models import Account, AccountStatus, Webhook
from ..errors import ForbiddenError
from .access import Access
from .accounts import AccountService
from .sync import SyncService, SyncState
from .webhooks import WebhookService
from .worker import SyncWorker, WorkerState


@dataclass(frozen=True)
class AccountHealth:
    account: Account
    sync: SyncState
    # Whether a sync pass does anything for the account.
    synced: bool
    # Whether a watcher waits for the server to report a change.
    watching: bool

    @property
    def attention(self) -> bool:
        """Whether a person should look at it."""
        return (
            self.account.status is not AccountStatus.CONNECTED
            or self.sync.last_error is not None
        )


@dataclass(frozen=True)
class ServiceStatus:
    accounts: list[AccountHealth]
    # None when the worker is switched off.
    worker: WorkerState | None
    # The caller's own webhooks, empty without webhooks.manage.
    webhooks: list[Webhook]

    @property
    def attention(self) -> list[AccountHealth]:
        return [health for health in self.accounts if health.attention]

    @property
    def failing(self) -> list[Webhook]:
        return [webhook for webhook in self.webhooks if webhook.last_error]


class StatusService:
    def __init__(
        self,
        accounts: AccountService,
        sync: SyncService,
        worker: SyncWorker | None,
        webhooks: WebhookService,
    ) -> None:
        self._accounts = accounts
        self._sync = sync
        self._worker = worker
        self._webhooks = webhooks

    def may_see(self, access: Access) -> bool:
        """The status is for callers who may list some account."""
        return access.anywhere("list_accounts")

    def status(self, access: Access) -> ServiceStatus:
        """The accounts the caller may list, the worker and the caller's
        webhooks."""
        if not self.may_see(access):
            raise ForbiddenError("missing right: list_accounts")
        worker = self._worker.state() if self._worker is not None else None
        watching = worker.watching if worker is not None else frozenset()
        accounts = [
            AccountHealth(
                account=account,
                sync=self._sync.state(account.id),
                synced=self._sync.watched(account.id),
                watching=account.id in watching,
            )
            for account in self._accounts.list(access)
        ]
        webhooks = (
            self._webhooks.list_webhooks(access)
            if access.allows("list_webhooks")
            else []
        )
        return ServiceStatus(accounts=accounts, worker=worker, webhooks=webhooks)
