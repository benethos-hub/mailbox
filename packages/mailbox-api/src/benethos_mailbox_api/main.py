"""Assembly: builds the app from its layers. Decides nothing else.

The one place that chooses implementations - which repository, which
provider registry - so tests and later deployments swap them here.
"""

from __future__ import annotations

import json

from fastapi import FastAPI
from fastapi.routing import APIRoute

from . import __version__
from .config import Settings
from .data.storage import (
    InMemoryAccountRepository,
    InMemoryRoleRepository,
    InMemoryTokenRepository,
    InMemoryUserRepository,
)
from .domain.accounts import AccountService
from .domain.auth import AuthService
from .domain.mailbox import MailboxService
from .web import include_routes
from .web.errors import install_error_handlers


def _operation_id(route: APIRoute) -> str:
    """The function name, e.g. ``list_messages``.

    Stable and readable ids matter: client generators name methods after them,
    and the MCP server maps its tools onto them.
    """
    return route.name


def create_app(
    settings: Settings | None = None,
    accounts: AccountService | None = None,
    auth: AuthService | None = None,
) -> FastAPI:
    app = FastAPI(
        title="Mailbox API",
        version=__version__,
        description="Unified REST API for several mail providers and accounts.",
        generate_unique_id_function=_operation_id,
    )
    settings = settings or Settings()
    accounts = accounts or AccountService(InMemoryAccountRepository())
    admin_key = settings.api_key.get_secret_value() if settings.api_key else None
    auth = auth or AuthService(
        InMemoryUserRepository(),
        InMemoryRoleRepository(),
        InMemoryTokenRepository(),
        admin_key=admin_key,
    )
    app.state.settings = settings
    app.state.auth = auth
    app.state.accounts = accounts
    app.state.mailbox = MailboxService(accounts)

    include_routes(app)
    install_error_handlers(app)
    return app


def openapi_json() -> str:
    """The OpenAPI document, formatted the way ``docs/openapi.json`` stores it."""
    return json.dumps(create_app().openapi(), indent=2, ensure_ascii=False) + "\n"
