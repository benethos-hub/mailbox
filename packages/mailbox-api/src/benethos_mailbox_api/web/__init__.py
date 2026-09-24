"""Web layer: HTTP and nothing else.

Checks input, calls the domain, answers. FastAPI is imported here and
nowhere else. ``routes`` holds one router per resource, ``schemas`` the
shapes that exist only at the HTTP boundary, ``errors`` the mapping from
domain errors to status codes, ``deps`` authentication and the services a
route needs. May import ``domain`` and ``data``.
"""

from __future__ import annotations

from fastapi import Depends, FastAPI
from fastapi.routing import APIRoute

from ..domain.permissions import permission_of
from .deps import authenticate
from .errors import DOCUMENTED_ERRORS
from .routes import accounts, health, mailbox, users

API_PREFIX = "/v1"


def include_routes(app: FastAPI) -> None:
    """Mount every router: ``/health`` open, everything else under ``/v1``.

    Every ``/v1`` route gets its right from the catalogue as ``x-permission``.
    A route missing from the catalogue stops the app from starting.
    """
    app.include_router(health.router)
    # Every /v1 route authenticates, even one that does not use the caller.
    protected = [Depends(authenticate)]
    for router in (users.router, accounts.router, mailbox.router):
        for route in router.routes:
            if isinstance(route, APIRoute):
                _declare_permission(route)
        app.include_router(
            router,
            prefix=API_PREFIX,
            dependencies=protected,
            responses=DOCUMENTED_ERRORS,
        )


def _declare_permission(route: APIRoute) -> None:
    permission = permission_of(route.name)
    if permission is None:
        raise RuntimeError(
            f"route {route.name} has no entry in the permission catalogue"
        )
    route.openapi_extra = {**(route.openapi_extra or {}), "x-permission": permission}
