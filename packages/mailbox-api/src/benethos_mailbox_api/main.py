"""Assembly: builds the app from its layers. Decides nothing else.

The one place that chooses implementations - which repositories, which
provider factory - so tests and deployments swap them here.
"""

from __future__ import annotations

import json
from dataclasses import dataclass

from fastapi import FastAPI
from fastapi.routing import APIRoute

from . import __version__
from .config import Settings
from .data.providers import ProviderFactory, build_provider
from .data.storage import (
    InMemoryAccountRepository,
    InMemoryRoleRepository,
    InMemoryTokenRepository,
    InMemoryUserRepository,
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


def build_services(
    settings: Settings, provider_factory: ProviderFactory = build_provider
) -> Services:
    user_repo = InMemoryUserRepository()
    role_repo = InMemoryRoleRepository()
    token_repo = InMemoryTokenRepository()
    admin_key = settings.api_key.get_secret_value() if settings.api_key else None
    accounts = AccountService(InMemoryAccountRepository(), provider_factory)
    auth = AuthService(user_repo, role_repo, token_repo, admin_key=admin_key)
    return Services(
        accounts=accounts,
        auth=auth,
        users=UserService(user_repo, role_repo, token_repo, accounts, auth),
        mailbox=MailboxService(accounts),
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
    app = FastAPI(
        title="Mailbox API",
        version=__version__,
        description="Unified REST API for several mail providers and accounts.",
        generate_unique_id_function=_operation_id,
    )
    settings = settings or Settings()
    services = services or build_services(settings)
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
    return json.dumps(create_app().openapi(), indent=2, ensure_ascii=False) + "\n"
