"""The state of the service, for the overview, the accounts list and the
dots of the sidebar (docs/UI.md, sections 3 and 5), and `GET /v1/status`.

It reads what the other services keep: the accounts, the sync state of
each, the worker and the caller's webhooks. Nothing is asked of a
provider for it.
"""

from __future__ import annotations

from dataclasses import dataclass

from ...data.models import Account, AccountStatus, Webhook
from ...errors import ForbiddenError, MailboxServiceError
from ..accounts import AccountService
from ..rights import Access
from ..sync import SyncService, SyncState, SyncWorker, WorkerState
from ..webhooks import WebhookService


@dataclass(frozen=True, slots=True)
class AccountHealth:
    account: Account
    sync: SyncState
    # Whether a sync pass does anything for the account.
    synced: bool
    # Whether a watcher waits for the server to report a change.
    watching: bool
    # Why the service cannot build the account's adapter, e.g. a Gmail
    # account without the Google client in the settings.
    problem: str | None = None

    @property
    def attention(self) -> bool:
        """Whether a person should look at it."""
        return (
            self.account.status is not AccountStatus.CONNECTED
            or self.sync.last_error is not None
            or self.problem is not None
        )


@dataclass(frozen=True, slots=True)
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


@dataclass(frozen=True, slots=True)
class Attention:
    """Whether something waits for a person, for the dots of the sidebar."""

    # An account the caller may see the status of needs a new sign-in,
    # cannot be reached or fails to sync.
    accounts: bool = False
    # One of the caller's webhooks fails.
    webhooks: bool = False


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

    def sync_of(self, access: Access, account_id: str) -> SyncState | None:
        """How the account's sync went, None when no pass does anything
        for it."""
        access.require("get_account", account_id)
        if not self._synced(account_id)[0]:
            return None
        return self._sync.state(account_id)

    def status(self, access: Access) -> ServiceStatus:
        """The accounts the caller may list and see the status of, the
        worker and the caller's webhooks."""
        if not access.sees_status():
            raise ForbiddenError("missing right: get_status")
        worker = self._worker.state() if self._worker is not None else None
        accounts = self._healths(self._accounts.list(access, may="get_status"), worker)
        return ServiceStatus(
            accounts=accounts, worker=worker, webhooks=self._own_webhooks(access)
        )

    def healths(
        self, access: Access, accounts: list[Account]
    ) -> dict[str, AccountHealth]:
        """How each of ``accounts`` fares, by its id, for those the caller
        may see the status of, e.g. a page of the accounts list."""
        worker = self._worker.state() if self._worker is not None else None
        seen = [a for a in accounts if access.allows("get_status", a.id)]
        return {health.account.id: health for health in self._healths(seen, worker)}

    def attention(self, access: Access) -> Attention:
        """Whether an account or a webhook of the caller's waits for a
        person. Nothing is asked of a provider for it."""
        accounts = access.sees_status() and any(
            health.attention
            for health in self._healths(
                self._accounts.list(access, may="get_status"), None
            )
        )
        webhooks = any(webhook.last_error for webhook in self._own_webhooks(access))
        return Attention(accounts=accounts, webhooks=webhooks)

    def _healths(
        self, accounts: list[Account], worker: WorkerState | None
    ) -> list[AccountHealth]:
        watching = worker.watching if worker is not None else frozenset()
        healths = []
        for account in accounts:
            synced, problem = self._synced(account.id)
            healths.append(
                AccountHealth(
                    account=account,
                    sync=self._sync.state(account.id),
                    synced=synced,
                    watching=account.id in watching,
                    problem=problem,
                )
            )
        return healths

    def _synced(self, account_id: str) -> tuple[bool, str | None]:
        """Whether a sync pass does anything for the account, and why
        not when its adapter cannot be built. Such an account is not
        synced, and every page still opens to remove it."""
        try:
            return self._sync.watched(account_id), None
        except MailboxServiceError as exc:
            return False, str(exc)

    def _own_webhooks(self, access: Access) -> list[Webhook]:
        if not access.allows("list_webhooks"):
            return []
        return self._webhooks.list_webhooks(access)
