"""Assembly: builds the app from its layers. Decides nothing else.

The one place that chooses implementations (which repositories, which
provider factory), so tests and deployments swap them here.
"""

from __future__ import annotations

import json
import logging
from collections.abc import AsyncIterator, Iterator, Mapping
from contextlib import asynccontextmanager, contextmanager
from dataclasses import dataclass, field

import anyio
from fastapi import FastAPI
from fastapi.routing import APIRoute

from . import __version__, web
from .config import Settings
from .data.discovery import SafeFetcher, default_sources, preset_hosts
from .data.http import ApiClient, Resolve, host_addresses
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
)
from .data.storage import Database, open_repositories
from .domain.accounts import AccountService
from .domain.adapters import Adapters
from .domain.auth import AuthService
from .domain.discovery import DiscoveryService
from .domain.idempotency import Idempotency
from .domain.mailbox import MailboxService
from .domain.oauth import OAuthService
from .domain.sending import SendControl
from .domain.sync import SyncService
from .domain.users import UserService
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
    vault: CredentialVault
    oauth: OAuthService
    worker: SyncWorker | None = None
    database: Database | None = None
    oauth_clients: Mapping[ProviderType, OAuthClient] = field(default_factory=dict)

    async def aclose(self) -> None:
        """Every connection and the database, when the service stops."""
        await self.adapters.close()
        for client in self.oauth_clients.values():
            await client.close()
        self.close()

    def close(self) -> None:
        """The database alone: for the command line, which connects to
        nothing."""
        if self.database is not None:
            self.database.close()


def build_services(
    settings: Settings,
    provider_factory: ProviderFactory = build_provider,
    discovery: DiscoveryService | None = None,
    oauth_clients: Mapping[ProviderType, OAuthClient] | None = None,
    resolve: Resolve | None = None,
) -> Services:
    """``resolve`` answers DNS for the host check that autodiscovery and the
    hosts of an account pass (CONCEPT 5.8, rule 6). Tests hand in a table."""
    repos = open_repositories(settings.storage, settings.database_path)
    vault = CredentialVault(repos.keys, repos.credentials, key_provider(settings))
    admin_key = settings.api_key.get_secret_value() if settings.api_key else None
    clients = oauth_clients if oauth_clients is not None else build_oauth(settings)
    # One guard for every connection the service makes to a host a user
    # typed: the lookups of autodiscovery and the servers of an account.
    fetcher = SafeFetcher(
        resolve=resolve or host_addresses,
        internal_hosts=settings.discovery_internal_hosts,
    )
    adapters = Adapters(repos.accounts, vault, provider_factory, oauth=clients)
    accounts = AccountService(
        repos.accounts, vault, adapters, repos.index, check_host=fetcher.checked_address
    )
    sync = SyncService(adapters, repos.index)
    auth = AuthService(repos.users, repos.roles, repos.tokens, admin_key=admin_key)
    return Services(
        accounts=accounts,
        adapters=adapters,
        auth=auth,
        users=UserService(repos.users, repos.roles, repos.tokens, adapters, auth),
        mailbox=MailboxService(
            adapters, sync, Idempotency(repos.idempotency), SendControl(repos.sends)
        ),
        discovery=discovery or build_discovery(settings, fetcher),
        sync=sync,
        worker=(
            SyncWorker(
                adapters, sync, interval=settings.sync_interval, push=settings.sync_idle
            )
            if settings.sync_interval
            else None
        ),
        vault=vault,
        oauth=OAuthService(accounts, adapters, clients),
        database=repos.database,
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
            "the master key comes from MAILBOX_SERVICE_MASTER_KEY; the environment "
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
        async with anyio.create_task_group() as background:
            if services.worker is not None:
                background.start_soon(services.worker.run)
            try:
                yield
            finally:
                # The worker first, so it opens nothing new while the
                # adapters close.
                background.cancel_scope.cancel()
        await services.aclose()

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


def openapi_json() -> str:
    """The OpenAPI document, formatted the way ``docs/openapi.json`` stores it."""
    app = create_app(Settings(storage="memory"))
    return json.dumps(app.openapi(), indent=2, ensure_ascii=False) + "\n"
