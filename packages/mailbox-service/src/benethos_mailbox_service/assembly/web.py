"""The app: FastAPI on the services, and the OpenAPI document."""

from __future__ import annotations

import json
from collections.abc import AsyncIterator
from contextlib import asynccontextmanager
from pathlib import Path

from fastapi import FastAPI
from fastapi.routing import APIRoute

from .. import __version__, web
from ..config import Settings
from ..data.logbook import LogBook
from ..data.secrets import EnvKeyProvider
from .domain import build_services
from .lifecycle import serving
from .services import Services


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
        async with serving(services, settings, settings_file):
            yield

    app = FastAPI(
        title="mailbox-service",
        version=__version__,
        description=(
            "Unified REST API for several mail providers and accounts. "
            "Requests are limited per token, and without one per client "
            "address. Past the limit the API answers "
            "`429` with `Retry-After`."
        ),
        generate_unique_id_function=_operation_id,
        lifespan=lifespan,
    )
    app.state.settings = settings
    app.state.services = services

    web.install(app)
    return app


def _operation_id(route: APIRoute) -> str:
    """The function name, e.g. ``list_messages``.

    Stable and readable ids matter: client generators name methods after them,
    and the MCP server maps its tools onto them.
    """
    return route.name


def openapi_json() -> str:
    """The OpenAPI document, formatted the way ``docs/openapi.json`` stores it.
    Built from the routes alone: no key, no OAuth app, nothing stored."""
    settings = Settings(storage="memory", sync_interval=0)
    services = build_services(settings, oauth_clients={}, keys=EnvKeyProvider(None))
    app = create_app(settings, services)
    return json.dumps(app.openapi(), indent=2, ensure_ascii=False) + "\n"
