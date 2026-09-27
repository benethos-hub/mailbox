"""Assembly: builds the app from its layers. Decides nothing else.

The one place that chooses implementations (which repositories, which
provider factory), so tests and deployments swap them here.
"""

from __future__ import annotations

import json
import logging
from collections.abc import AsyncIterator, Callable, Iterator, Mapping
from contextlib import ExitStack, asynccontextmanager, contextmanager
from dataclasses import dataclass, field
from datetime import datetime
from functools import partial

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
)
from .data.storage import (
    MessageIndexRepository,
    Repositories,
    Store,
    open_repositories,
)
from .domain.accounts import AccountService
from .domain.adapters import Adapters
from .domain.auth import AuthService
from .domain.changes import ChangeFeed
from .domain.delivery import Retries, WebhookDispatcher
from .domain.discovery import DiscoveryService
from .domain.idempotency import Idempotency
from .domain.mailbox import MailboxService
from .domain.oauth import OAuthService
from .domain.passwords import Passwords
from .domain.recovery import RecoveryKey
from .domain.sending import SendControl
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
    # Every repository behind the services, closed with them.
    repositories: Repositories
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
) -> Services:
    """``resolve`` answers DNS for the host check that autodiscovery and the
    hosts of an account pass (CONCEPT 5.8, rule 6), ``lookup`` the same
    for the check at every connection to a mail server, which adapters
    make without ``provider_factory``. Tests hand in tables. ``keys``
    replaces the key provider the settings name, ``clock`` the time of
    every service."""
    repos = open_repositories(settings.storage, settings.database_path)
    vault = CredentialVault(
        repos.keys, repos.credentials, keys or key_provider(settings)
    )
    clients = oauth_clients if oauth_clients is not None else build_oauth(settings)
    # One guard for every connection the service makes to a host a user
    # typed: the lookups of autodiscovery and the servers of an account.
    fetcher = SafeFetcher(
        resolve=resolve or host_addresses,
        internal_hosts=settings.discovery_internal_hosts,
        lookup=lookup or host_addresses_now,
    )
    changes = ChangeFeed(repos.changes, days=settings.changes_days, clock=clock)
    if provider_factory is None:
        provider_factory = partial(build_provider, pick=fetcher.connect_address)
    adapters = Adapters(
        repos.accounts, vault, provider_factory, oauth=clients, changes=changes
    )
    sync = SyncService(adapters, repos.index, feed=changes, clock=clock)
    accounts = AccountService(
        repos.accounts,
        vault,
        adapters,
        sync,
        check_host=fetcher.checked_address,
        idempotency=repos.idempotency,
        changes=changes,
    )
    auth = AuthService(
        repos.users,
        repos.roles,
        repos.tokens,
        Passwords(repos.passwords, password_hasher, clock=clock),
        clock=clock,
    )
    worker = (
        SyncWorker(
            adapters,
            sync,
            interval=settings.sync_interval,
            push=settings.sync_idle,
            clock=clock,
        )
        if settings.sync_interval
        else None
    )
    webhooks = WebhookService(repos.webhooks, vault, changes, clock=clock)
    return Services(
        accounts=accounts,
        adapters=adapters,
        auth=auth,
        users=UserService(
            repos.users, repos.roles, repos.tokens, adapters, auth, repos.webhooks
        ),
        mailbox=MailboxService(
            adapters,
            sync,
            Idempotency(repos.idempotency, clock=clock),
            SendControl(repos.sends, clock=clock),
            clock=clock,
        ),
        discovery=discovery or build_discovery(settings, fetcher),
        sync=sync,
        index=repos.index,
        changes=changes,
        worker=worker,
        vault=vault,
        oauth=OAuthService(accounts, adapters, clients, clock=clock),
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
        ),
        status=StatusService(accounts, sync, worker, webhooks),
        recovery=RecoveryKey(auth, vault),
        repositories=repos,
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
        app = App(
            endpoints=sign_in(ProviderType.MICROSOFT, settings.oauth_microsoft_tenant),
            client_id=settings.oauth_microsoft_client_id,
            client_secret=settings.oauth_microsoft_secret(),
        )
        clients[ProviderType.MICROSOFT] = OAuthClient(app, ApiClient())
    return clients


def build_discovery(settings: Settings, fetcher: SafeFetcher) -> DiscoveryService:
    return DiscoveryService(
        default_sources(fetcher, ispdb=settings.discovery_ispdb),
        probe=probe_server,
        check_host=fetcher.checked_address,
        trusted_hosts=preset_hosts(),
    )


def key_provider(settings: Settings) -> KeyProvider:
    """The key provider the settings name."""
    if settings.key_provider == "env":
        logging.getLogger(__name__).warning(
            "the master key comes from MAILBOX_SERVICE_MASTER_KEY. The environment "
            "shows up in process listings and container inspection"
        )
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
    settings: Settings | None = None, services: Services | None = None
) -> FastAPI:
    settings = settings or Settings()
    services = services or build_services(settings)

    @asynccontextmanager
    async def lifespan(_: FastAPI) -> AsyncIterator[None]:
        with ExitStack() as serving:
            if services.store is not None and not serving.enter_context(
                services.store.serving()
            ):
                logging.getLogger(__name__).warning(
                    "another service uses this database: a restore cannot "
                    "tell that this one runs"
                )
            async with _running(services):
                yield

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
            background.start_soon(services.worker.run)
        background.start_soon(services.deliveries.run)
        try:
            yield
        finally:
            # The worker first, so it opens nothing new while the
            # adapters close.
            background.cancel_scope.cancel()
    await services.aclose()


def openapi_json() -> str:
    """The OpenAPI document, formatted the way ``docs/openapi.json`` stores it.
    Built from the routes alone: no key, no OAuth app, nothing stored."""
    settings = Settings(storage="memory", sync_interval=0)
    services = build_services(settings, oauth_clients={}, keys=EnvKeyProvider(None))
    app = create_app(settings, services)
    return json.dumps(app.openapi(), indent=2, ensure_ascii=False) + "\n"
