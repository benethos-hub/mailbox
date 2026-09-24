"""Assembly: builds the app from its layers. Decides nothing else.

The one place that chooses implementations - which repositories, which
provider factory - so tests and deployments swap them here.
"""

from __future__ import annotations

import json
import logging
from collections.abc import AsyncIterator
from contextlib import asynccontextmanager
from dataclasses import dataclass

from fastapi import FastAPI
from fastapi.routing import APIRoute

from . import __version__
from .config import Settings
from .data.discovery import SafeFetcher, default_sources, preset_hosts
from .data.providers import ProviderFactory, build_provider, probe_server
from .data.secrets import (
    CredentialVault,
    EnvKeyProvider,
    FileKeyProvider,
    KeyProvider,
    KeyringKeyProvider,
)
from .data.storage import (
    AccountRepository,
    CredentialRepository,
    Database,
    InMemoryAccountRepository,
    InMemoryCredentialRepository,
    InMemoryKeyRepository,
    InMemoryRoleRepository,
    InMemoryTokenRepository,
    InMemoryUserRepository,
    KeyRepository,
    RoleRepository,
    SqliteAccountRepository,
    SqliteCredentialRepository,
    SqliteKeyRepository,
    SqliteRoleRepository,
    SqliteTokenRepository,
    SqliteUserRepository,
    TokenRepository,
    UserRepository,
)
from .domain.accounts import AccountService
from .domain.auth import AuthService
from .domain.discovery import DiscoveryService
from .domain.mailbox import MailboxService
from .domain.users import UserService
from .web import include_routes
from .web.errors import install_error_handlers


@dataclass(frozen=True)
class Services:
    accounts: AccountService
    auth: AuthService
    users: UserService
    mailbox: MailboxService
    discovery: DiscoveryService
    vault: CredentialVault
    database: Database | None = None

    def close(self) -> None:
        if self.database is not None:
            self.database.close()


def build_services(
    settings: Settings,
    provider_factory: ProviderFactory = build_provider,
    discovery: DiscoveryService | None = None,
) -> Services:
    account_repo: AccountRepository
    user_repo: UserRepository
    role_repo: RoleRepository
    token_repo: TokenRepository
    key_repo: KeyRepository
    credential_repo: CredentialRepository
    db: Database | None = None
    if settings.storage == "memory":
        account_repo = InMemoryAccountRepository()
        user_repo = InMemoryUserRepository()
        role_repo = InMemoryRoleRepository()
        token_repo = InMemoryTokenRepository()
        key_repo = InMemoryKeyRepository()
        credential_repo = InMemoryCredentialRepository()
    else:
        db = Database(settings.database_path)
        account_repo = SqliteAccountRepository(db)
        user_repo = SqliteUserRepository(db)
        role_repo = SqliteRoleRepository(db)
        token_repo = SqliteTokenRepository(db)
        key_repo = SqliteKeyRepository(db)
        credential_repo = SqliteCredentialRepository(db)
    vault = CredentialVault(key_repo, credential_repo, key_provider(settings))
    admin_key = settings.api_key.get_secret_value() if settings.api_key else None
    accounts = AccountService(account_repo, vault, provider_factory)
    auth = AuthService(user_repo, role_repo, token_repo, admin_key=admin_key)
    return Services(
        accounts=accounts,
        auth=auth,
        users=UserService(user_repo, role_repo, token_repo, accounts, auth),
        mailbox=MailboxService(accounts),
        discovery=discovery or build_discovery(settings),
        vault=vault,
        database=db,
    )


def build_discovery(settings: Settings) -> DiscoveryService:
    fetcher = SafeFetcher(internal_hosts=settings.discovery_internal_hosts)
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
            "the master key comes from MAILBOX_API_MASTER_KEY; the environment "
            "shows up in process listings and container inspection"
        )
        value = settings.master_key.get_secret_value() if settings.master_key else None
        return EnvKeyProvider(value)
    if settings.key_provider == "file":
        if settings.key_file is None:
            raise ValueError(
                "MAILBOX_API_KEY_FILE must be set for the file key provider"
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
        yield
        services.close()

    app = FastAPI(
        title="Mailbox API",
        version=__version__,
        description="Unified REST API for several mail providers and accounts.",
        generate_unique_id_function=_operation_id,
        lifespan=lifespan,
    )
    app.state.settings = settings
    app.state.accounts = services.accounts
    app.state.auth = services.auth
    app.state.users = services.users
    app.state.mailbox = services.mailbox
    app.state.discovery = services.discovery

    include_routes(app)
    install_error_handlers(app)
    return app


def openapi_json() -> str:
    """The OpenAPI document, formatted the way ``docs/openapi.json`` stores it."""
    app = create_app(Settings(storage="memory"))
    return json.dumps(app.openapi(), indent=2, ensure_ascii=False) + "\n"
