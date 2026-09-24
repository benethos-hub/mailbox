"""Assembly: builds the app from its layers. Decides nothing else.

The one place that chooses implementations - which repositories, which
provider factory - so tests and deployments swap them here.
"""

from __future__ import annotations

import json
from collections.abc import AsyncIterator
from contextlib import asynccontextmanager
from dataclasses import dataclass

from fastapi import FastAPI
from fastapi.routing import APIRoute

from . import __version__
from .config import Settings
from .data.providers import ProviderFactory, build_provider
from .data.storage import (
    AccountRepository,
    Database,
    InMemoryAccountRepository,
    InMemoryRoleRepository,
    InMemoryTokenRepository,
    InMemoryUserRepository,
    RoleRepository,
    SqliteAccountRepository,
    SqliteRoleRepository,
    SqliteTokenRepository,
    SqliteUserRepository,
    TokenRepository,
    UserRepository,
)
from .domain.accounts import AccountService
from .domain.auth import AuthService
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
    database: Database | None = None

    def close(self) -> None:
        if self.database is not None:
            self.database.close()


def build_services(
    settings: Settings, provider_factory: ProviderFactory = build_provider
) -> Services:
    account_repo: AccountRepository
    user_repo: UserRepository
    role_repo: RoleRepository
    token_repo: TokenRepository
    db: Database | None = None
    if settings.storage == "memory":
        account_repo = InMemoryAccountRepository()
        user_repo = InMemoryUserRepository()
        role_repo = InMemoryRoleRepository()
        token_repo = InMemoryTokenRepository()
    else:
        db = Database(settings.database_path)
        account_repo = SqliteAccountRepository(db)
        user_repo = SqliteUserRepository(db)
        role_repo = SqliteRoleRepository(db)
        token_repo = SqliteTokenRepository(db)
    admin_key = settings.api_key.get_secret_value() if settings.api_key else None
    accounts = AccountService(account_repo, provider_factory)
    auth = AuthService(user_repo, role_repo, token_repo, admin_key=admin_key)
    return Services(
        accounts=accounts,
        auth=auth,
        users=UserService(user_repo, role_repo, token_repo, accounts, auth),
        mailbox=MailboxService(accounts),
        database=db,
    )


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

    include_routes(app)
    install_error_handlers(app)
    return app


def openapi_json() -> str:
    """The OpenAPI document, formatted the way ``docs/openapi.json`` stores it."""
    app = create_app(Settings(storage="memory"))
    return json.dumps(app.openapi(), indent=2, ensure_ascii=False) + "\n"
