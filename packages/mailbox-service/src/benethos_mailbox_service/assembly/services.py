"""``Services``: every service of the domain, as the web layer and the
command line reach them."""

from __future__ import annotations

from collections.abc import Callable, Mapping
from dataclasses import dataclass, field

from ..data.models import ProviderType
from ..data.providers import OAuthClient
from ..data.secrets import CredentialVault
from ..data.storage import MessageIndexRepository, Repositories, Store
from ..domain.accounts import AccountService, Adapters, OAuthService
from ..domain.activity import ActivityLog, Audit
from ..domain.auth import AuthService
from ..domain.changes import ChangeFeed
from ..domain.discovery import DiscoveryService
from ..domain.mailbox import MailboxService
from ..domain.sync import SyncService, SyncWorker
from ..domain.system import RecoveryKey, ServiceLog, StatusService
from ..domain.users import (
    PasswordService,
    RoleService,
    SecondFactorService,
    TokenService,
    TotpService,
    UserService,
)
from ..domain.webhooks import WebhookDispatcher, WebhookService


@dataclass(frozen=True)
class Services:
    accounts: AccountService
    adapters: Adapters
    auth: AuthService
    users: UserService
    roles: RoleService
    tokens: TokenService
    passwords: PasswordService
    factors: SecondFactorService
    totp: TotpService
    mailbox: MailboxService
    discovery: DiscoveryService
    sync: SyncService
    index: MessageIndexRepository  # the store behind sync
    changes: ChangeFeed
    vault: CredentialVault
    oauth: OAuthService
    webhooks: WebhookService
    deliveries: WebhookDispatcher
    status: StatusService
    recovery: RecoveryKey
    log: ServiceLog
    # The audit of administration, read by list_activity.
    audit: Audit
    # Every repository behind the services, closed with them.
    repositories: Repositories
    activity: ActivityLog = field(default_factory=ActivityLog)
    worker: SyncWorker | None = None
    oauth_clients: Mapping[ProviderType, OAuthClient] = field(default_factory=dict)
    # What removes records older than the days to keep: the audit, the
    # change feed, the audit of sends. Each runs once when the service
    # starts, then as new records come in.
    purges: tuple[Callable[[], None], ...] = ()

    @property
    def store(self) -> Store | None:
        """What holds the records, for a backup. None in memory."""
        return self.repositories.store

    async def aclose(self) -> None:
        """Every connection and the database, when the service stops."""
        await self.adapters.close()
        for client in self.oauth_clients.values():
            await client.close()
        self.close()

    def close(self) -> None:
        """The store alone: for the command line, which connects to
        nothing."""
        self.repositories.close()
