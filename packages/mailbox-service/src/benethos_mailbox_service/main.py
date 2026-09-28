"""Assembly: builds the app from its layers. Decides nothing else.

The one place that chooses implementations (which repositories, which
provider factory), so tests and deployments swap them here.
"""

from __future__ import annotations

import json
from collections.abc import AsyncIterator, Awaitable, Callable, Iterator, Mapping
from contextlib import ExitStack, asynccontextmanager, contextmanager
from dataclasses import dataclass, field
from datetime import datetime
from functools import partial
from pathlib import Path

import anyio
from fastapi import FastAPI
from fastapi.routing import APIRoute

from . import __version__, web
from .common.clock import utc_now
from .config import Settings
from .data.discovery import default_sources, preset_hosts
from .data.http import (
    ApiClient,
    Lookup,
    Resolve,
    SafeFetcher,
    WebhookPoster,
    host_addresses,
    host_addresses_now,
)
from .data.logbook import LogBook
from .data.models import ProviderType
from .data.providers import (
    App,
    OAuthClient,
    ProviderFactory,
    build_provider,
    probe_server,
    sign_in,
)
from .data.secrets import (
    CredentialVault,
    EnvKeyProvider,
    FileKeyProvider,
    KeyProvider,
    KeyProviderError,
    KeyringKeyProvider,
    PasswordHasher,
    redact,
)
from .data.storage import (
    MessageIndexRepository,
    Repositories,
    Store,
    open_repositories,
)
from .domain.accounts import AccountService
from .domain.activity import DISPATCHER, SERVICE, WORKER, ActivityLog, Actor
from .domain.activity.catalogue import service as said
from .domain.adapters import Adapters
from .domain.auth import AuthService, Passwords
from .domain.changes import ChangeFeed
from .domain.delivery import Retries, WebhookDispatcher
from .domain.discovery import DiscoveryService
from .domain.idempotency import Idempotency
from .domain.mailbox import MailboxService
from .domain.oauth import OAuthService
from .domain.recovery import RecoveryKey
from .domain.sending import SendControl
from .domain.servicelog import ServiceLog
from .domain.status import StatusService
from .domain.sync import SyncService
from .domain.users import UserService
from .domain.webhooks import WebhookService
from .domain.worker import SyncWorker


@dataclass(frozen=True)
class Services:
    accounts: AccountService
    adapters: Adapters
    auth: AuthService
    users: UserService
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
    # Every repository behind the services, closed with them.
    repositories: Repositories
    activity: ActivityLog = field(default_factory=ActivityLog)
    worker: SyncWorker | None = None
    oauth_clients: Mapping[ProviderType, OAuthClient] = field(default_factory=dict)

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
    activity = ActivityLog(clock)
    repos = open_repositories(settings.storage, settings.database_path)
    migrated = repos.store.migrated if repos.store is not None else None
    if migrated is not None:
        activity.record(
            said.SchemaMigrated(
                by=SERVICE,
                before=migrated.before,
                after=migrated.after,
                notes=migrated.notes,
            )
        )
    vault = CredentialVault(
        repos.keys, repos.credentials, keys or key_provider(settings, activity)
    )
    clients = oauth_clients if oauth_clients is not None else build_oauth(settings)
    # One guard for every connection the service makes to a host a user
    # typed: the lookups of autodiscovery and the servers of an account.
    fetcher = SafeFetcher(
        resolve=resolve or host_addresses,
        internal_hosts=settings.discovery_internal_hosts,
        lookup=lookup or host_addresses_now,
    )
    changes = ChangeFeed(
        repos.changes, days=settings.changes_days, clock=clock, activity=activity
    )
    if provider_factory is None:
        provider_factory = partial(build_provider, pick=fetcher.connect_address)
    adapters = Adapters(
        repos.accounts,
        vault,
        provider_factory,
        oauth=clients,
        changes=changes,
        activity=activity,
    )
    sync = SyncService(
        adapters, repos.index, feed=changes, clock=clock, activity=activity
    )
    accounts = AccountService(
        repos.accounts,
        vault,
        adapters,
        sync,
        check_host=fetcher.checked_address,
        idempotency=repos.idempotency,
        changes=changes,
        activity=activity,
    )
    auth = AuthService(
        repos.users,
        repos.roles,
        repos.tokens,
        Passwords(repos.passwords, password_hasher, clock=clock),
        clock=clock,
        activity=activity,
    )
    worker = (
        SyncWorker(
            adapters,
            sync,
            interval=settings.sync_interval,
            push=settings.sync_idle,
            clock=clock,
            activity=activity,
        )
        if settings.sync_interval
        else None
    )
    webhooks = WebhookService(
        repos.webhooks, vault, changes, clock=clock, activity=activity
    )
    return Services(
        accounts=accounts,
        adapters=adapters,
        auth=auth,
        users=UserService(
            repos.users,
            repos.roles,
            repos.tokens,
            adapters,
            auth,
            repos.webhooks,
            activity=activity,
        ),
        mailbox=MailboxService(
            adapters,
            sync,
            Idempotency(repos.idempotency, clock=clock, activity=activity),
            SendControl(repos.sends, clock=clock, activity=activity),
            clock=clock,
            activity=activity,
        ),
        discovery=discovery or build_discovery(settings, fetcher, activity),
        sync=sync,
        index=repos.index,
        changes=changes,
        worker=worker,
        vault=vault,
        oauth=OAuthService(accounts, adapters, clients, clock=clock, activity=activity),
        webhooks=webhooks,
        deliveries=WebhookDispatcher(
            repos.webhooks,
            vault,
            changes,
            WebhookPoster(
                resolve=resolve or host_addresses, timeout=settings.webhook_timeout
            ),
            access_of=auth.access_of,
            account_ids=adapters.ids,
            retries=Retries(
                attempts=settings.webhook_attempts,
                first_retry=settings.webhook_first_retry,
                longest_retry=settings.webhook_longest_retry,
            ),
            clock=clock,
            activity=activity,
        ),
        status=StatusService(accounts, sync, worker, webhooks),
        recovery=RecoveryKey(auth, vault),
        log=ServiceLog(logbook or LogBook(), activity),
        repositories=repos,
        activity=activity,
        oauth_clients=clients,
    )


@contextmanager
def opened(settings: Settings) -> Iterator[Services]:
    """The services for one command on the host, closed afterwards."""
    services = build_services(settings)
    try:
        yield services
    finally:
        services.close()


def build_oauth(settings: Settings) -> dict[ProviderType, OAuthClient]:
    """The OAuth apps the settings name, one per provider."""
    clients: dict[ProviderType, OAuthClient] = {}
    if settings.oauth_microsoft_client_id:
        secret = settings.oauth_microsoft_secret()
        if secret is not None:
            redact.note(secret.get_secret_value())
        app = App(
            endpoints=sign_in(ProviderType.MICROSOFT, settings.oauth_microsoft_tenant),
            client_id=settings.oauth_microsoft_client_id,
            client_secret=secret,
        )
        clients[ProviderType.MICROSOFT] = OAuthClient(app, ApiClient())
    return clients


def build_discovery(
    settings: Settings, fetcher: SafeFetcher, activity: ActivityLog | None = None
) -> DiscoveryService:
    return DiscoveryService(
        default_sources(fetcher, ispdb=settings.discovery_ispdb),
        probe=probe_server,
        check_host=fetcher.checked_address,
        trusted_hosts=preset_hosts(),
        activity=activity,
    )


def key_provider(
    settings: Settings, activity: ActivityLog | None = None
) -> KeyProvider:
    """The key provider the settings name."""
    if settings.key_provider == "env":
        (activity or ActivityLog()).record(said.MasterKeyFromEnvironment(by=SERVICE))
        value = settings.master_key.get_secret_value() if settings.master_key else None
        return EnvKeyProvider(value)
    if settings.key_provider == "file":
        if settings.key_file is None:
            raise KeyProviderError(
                "MAILBOX_SERVICE_KEY_FILE must be set for the file key provider"
            )
        return FileKeyProvider(settings.key_file)
    return KeyringKeyProvider()


def _operation_id(route: APIRoute) -> str:
    """The function name, e.g. ``list_messages``.

    Stable and readable ids matter: client generators name methods after them,
    and the MCP server maps its tools onto them.
    """
    return route.name


def create_app(
    settings: Settings | None = None,
    services: Services | None = None,
    logbook: LogBook | None = None,
    settings_file: Path | None = None,
) -> FastAPI:
    """The app on ``services``, else on services built from ``settings``
    with ``logbook`` behind the log page. ``settings_file`` is where the
    settings came from, for the log."""
    settings = settings or Settings()
    services = services or build_services(settings, logbook=logbook)

    @asynccontextmanager
    async def lifespan(_: FastAPI) -> AsyncIterator[None]:
        with ExitStack() as serving:
            store = services.store
            if store is not None and not serving.enter_context(store.serving()):
                services.activity.record(said.DatabaseShared(by=SERVICE))
            services.activity.record(
                said.ServiceStarted(
                    by=SERVICE,
                    settings=str(settings_file) if settings_file else None,
                    database=str(settings.database_path) if store else None,
                    schema=store.schema_version() if store else None,
                )
            )
            try:
                async with _running(services):
                    yield
            finally:
                services.activity.record(said.ServiceStopped(by=SERVICE))

    app = FastAPI(
        title="Mailbox Service",
        version=__version__,
        description="Unified REST API for several mail providers and accounts.",
        generate_unique_id_function=_operation_id,
        lifespan=lifespan,
    )
    app.state.settings = settings
    app.state.services = services

    web.install(app)
    return app


@asynccontextmanager
async def _running(services: Services) -> AsyncIterator[None]:
    """The background work while the app serves, then every connection
    closed."""
    async with anyio.create_task_group() as background:
        if services.worker is not None:
            background.start_soon(_loop, services.activity, WORKER, services.worker.run)
        background.start_soon(
            _loop, services.activity, DISPATCHER, services.deliveries.run
        )
        try:
            yield
        finally:
            # The worker first, so it opens nothing new while the
            # adapters close.
            background.cancel_scope.cancel()
    await services.aclose()


async def _loop(
    activity: ActivityLog, by: Actor, run: Callable[[], Awaitable[None]]
) -> None:
    """A background loop, which runs until the service stops. Should it
    end otherwise, the log says so."""
    try:
        await run()
    except Exception as exc:
        activity.record(said.LoopEnded(by=by, error=exc))
        raise


def openapi_json() -> str:
    """The OpenAPI document, formatted the way ``docs/openapi.json`` stores it.
    Built from the routes alone: no key, no OAuth app, nothing stored."""
    settings = Settings(storage="memory", sync_interval=0)
    services = build_services(settings, oauth_clients={}, keys=EnvKeyProvider(None))
    app = create_app(settings, services)
    return json.dumps(app.openapi(), indent=2, ensure_ascii=False) + "\n"
