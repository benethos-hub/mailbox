"""The services of the domain, built on the records and the way out:
``build_services``, the one place that wires them together."""

from __future__ import annotations

from collections.abc import Callable, Mapping
from dataclasses import dataclass
from datetime import datetime, timedelta

from ..common.clock import utc_now
from ..config import Settings
from ..data.logbook import LogBook
from ..data.models import ProviderType
from ..data.protocols import Lookup, Resolve, SafeFetcher
from ..data.providers import OAuthClient, ProviderFactory
from ..data.secrets import CredentialVault, KeyProvider, PasswordHasher
from ..data.storage import Repositories, open_repositories
from ..domain.accounts import AccountService, Adapters, OAuthService
from ..domain.activity import ActivityLog
from ..domain.auth import AuthService, Passwords, SecondFactors, SignInThrottle
from ..domain.changes import ChangeFeed
from ..domain.discovery import DiscoveryService
from ..domain.mailbox import Idempotency, MailboxService, SendControl
from ..domain.sync import SyncService, SyncWorker
from ..domain.system import RecoveryKey, ServiceLog, StatusService
from ..domain.users import (
    Effective,
    PasswordService,
    RoleService,
    SecondFactorService,
    TokenService,
    UserRules,
    UserService,
)
from ..domain.webhooks import Retries, WebhookDispatcher, WebhookService
from . import providers, secrets
from .services import Services
from .storage import storage


def build_services(
    settings: Settings,
    provider_factory: ProviderFactory | None = None,
    discovery: DiscoveryService | None = None,
    oauth_clients: Mapping[ProviderType, OAuthClient] | None = None,
    resolve: Resolve | None = None,
    lookup: Lookup | None = None,
    password_hasher: PasswordHasher | None = None,
    keys: KeyProvider | None = None,
    clock: Callable[[], datetime] = utc_now,
    logbook: LogBook | None = None,
) -> Services:
    """``resolve`` answers DNS for the host check that autodiscovery and the
    hosts of an account pass (CONCEPT 5.8, rule 6), ``lookup`` the same
    for the check at every connection to a mail server, which adapters
    make without ``provider_factory``. Tests hand in tables. ``keys``
    replaces the key provider the settings name, ``clock`` the time of
    every service. ``logbook`` holds the log lines the log page shows:
    ``serve`` hands in the one its log writes to."""
    repositories = open_repositories(settings.storage, settings.database_path)
    try:
        records = storage(repositories, settings, clock)
        base = _Base(settings, repositories, records.activity, clock)
        fetcher = providers.guard(settings, resolve, lookup)
        clients = (
            oauth_clients
            if oauth_clients is not None
            else providers.build_oauth(settings)
        )
        vault = secrets.vault(repositories, settings, records.activity, keys)
        changes = ChangeFeed(
            repositories.changes,
            days=settings.changes_days,
            clock=clock,
            activity=records.activity,
        )
        adapters = Adapters(
            repositories.accounts,
            vault,
            provider_factory or providers.provider_factory(settings, fetcher),
            oauth=clients,
            changes=changes,
            activity=records.activity,
        )
        offered = providers.offered_providers(settings)
        services = _Domain(
            base, vault, changes, adapters, fetcher, password_hasher, offered, resolve
        )
        return Services(
            accounts=services.accounts,
            adapters=adapters,
            auth=services.auth,
            users=services.users,
            roles=services.roles,
            tokens=services.tokens,
            passwords=services.passwords,
            factors=services.factors,
            mailbox=services.mailbox,
            discovery=discovery
            or providers.build_discovery(
                settings, fetcher, records.activity, offered=offered
            ),
            sync=services.sync,
            index=repositories.index,
            changes=changes,
            worker=services.worker,
            vault=vault,
            oauth=OAuthService(
                services.accounts,
                adapters,
                clients,
                clock=clock,
                activity=records.activity,
            ),
            webhooks=services.webhooks,
            deliveries=services.deliveries,
            status=StatusService(
                services.accounts,
                services.sync,
                services.worker,
                services.webhooks,
            ),
            recovery=RecoveryKey(services.auth, vault),
            log=ServiceLog(logbook or LogBook(), records.activity),
            audit=records.audit,
            repositories=repositories,
            activity=records.activity,
            oauth_clients=clients,
            purges=(records.activity.purge, changes.purge, services.sends.purge),
        )
    except BaseException:
        # A part that cannot be built, such as a client secret file that
        # is missing, leaves no database open behind it.
        repositories.close()
        raise


@dataclass(frozen=True)
class _Base:
    """What every service is built on."""

    settings: Settings
    repositories: Repositories
    activity: ActivityLog
    clock: Callable[[], datetime]


class _Domain:
    """The services of the domain on ``base``, built in the order in which
    they need each other."""

    def __init__(
        self,
        base: _Base,
        vault: CredentialVault,
        changes: ChangeFeed,
        adapters: Adapters,
        fetcher: SafeFetcher,
        password_hasher: PasswordHasher | None,
        offered: frozenset[ProviderType] | None,
        resolve: Resolve | None,
    ) -> None:
        self._base = base
        self._vault = vault
        self._changes = changes
        self._adapters = adapters
        self._fetcher = fetcher
        settings, repositories = base.settings, base.repositories
        clock, activity = base.clock, base.activity
        self.sync = SyncService(
            adapters, repositories.index, feed=changes, clock=clock, activity=activity
        )
        factors = SecondFactors(repositories.factors, vault, clock=clock)
        self.auth = _auth(base, password_hasher, factors)
        self.sends = SendControl(
            repositories.sends, clock=clock, activity=activity, days=settings.audit_days
        )
        rules = UserRules(repositories.users, repositories.roles)
        self.passwords = PasswordService(repositories.users, self.auth, rules, activity)
        self.factors = SecondFactorService(
            repositories.users, self.auth, factors, rules, activity
        )
        self.tokens = TokenService(repositories.tokens, self.auth, rules, activity)
        self.roles = RoleService(repositories.roles, rules, activity)
        self.users = UserService(
            repositories.users,
            repositories.roles,
            repositories.tokens,
            repositories.webhooks,
            self.auth,
            self.passwords,
            Effective(adapters, sent=self.sends.sent_recently),
            rules,
            activity,
        )
        self.worker = _worker(base, adapters, self.sync)
        self.accounts = self._account_service(offered)
        self.webhooks = WebhookService(
            repositories.webhooks, vault, changes, clock=clock, activity=activity
        )
        self.mailbox = MailboxService(
            adapters,
            self.sync,
            Idempotency(repositories.idempotency, clock=clock, activity=activity),
            self.sends,
            clock=clock,
            activity=activity,
        )
        self.deliveries = self._dispatcher(resolve)

    def _account_service(
        self, offered: frozenset[ProviderType] | None
    ) -> AccountService:
        worker, sync = self.worker, self.sync

        def deleted(account_id: str) -> None:
            sync.forget_account(account_id)
            if worker is not None:
                worker.forget(account_id)

        return AccountService(
            self._base.repositories.accounts,
            self._vault,
            self._adapters,
            on_delete=deleted,
            on_connect=self.users.connected,
            on_ready=worker.take_up if worker is not None else None,
            check_host=self._fetcher.checked_address,
            idempotency=self._base.repositories.idempotency,
            changes=self._changes,
            activity=self._base.activity,
            offered=offered,
        )

    def _dispatcher(self, resolve: Resolve | None) -> WebhookDispatcher:
        settings = self._base.settings
        return WebhookDispatcher(
            self._base.repositories.webhooks,
            self._vault,
            self._changes,
            providers.poster(settings, resolve),
            access_of=self.auth.access_of,
            account_ids=self._adapters.ids,
            hearing=self.mailbox.hearing,
            retries=Retries(
                attempts=settings.webhook_attempts,
                first_retry=settings.webhook_first_retry,
                longest_retry=settings.webhook_longest_retry,
            ),
            clock=self._base.clock,
            activity=self._base.activity,
        )


def _auth(
    base: _Base, password_hasher: PasswordHasher | None, factors: SecondFactors
) -> AuthService:
    settings, repositories, clock = base.settings, base.repositories, base.clock
    lockout = timedelta(minutes=settings.sign_in_lockout_minutes)
    return AuthService(
        repositories.users,
        repositories.roles,
        repositories.tokens,
        Passwords(
            repositories.passwords,
            password_hasher,
            clock=clock,
            at_once=settings.password_hashes_at_once,
        ),
        clock=clock,
        throttle=SignInThrottle(
            settings.sign_in_failures, window=lockout, lockout=lockout, clock=clock
        ),
        names=SignInThrottle(
            settings.sign_in_failures,
            window=lockout,
            lockout=timedelta(seconds=settings.sign_in_name_wait),
            clock=clock,
        ),
        activity=base.activity,
        factors=factors,
    )


def _worker(base: _Base, adapters: Adapters, sync: SyncService) -> SyncWorker | None:
    """The background sync, None when the settings switch it off."""
    settings = base.settings
    if not settings.sync_interval:
        return None
    return SyncWorker(
        adapters,
        sync,
        interval=settings.sync_interval,
        push=settings.sync_idle,
        watchers=settings.sync_watchers,
        clock=base.clock,
        activity=base.activity,
    )
