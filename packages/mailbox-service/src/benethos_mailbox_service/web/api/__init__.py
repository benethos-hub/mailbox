"""The JSON API: ``/health`` open, everything else under ``/v1``.

``routes`` holds one router per resource, ``schemas`` the shapes that
exist only at the HTTP boundary, ``errors`` the mapping from domain errors
to status codes and the envelope, ``deps`` authentication by bearer token
and the services a route needs.
"""

from __future__ import annotations

from fastapi import Depends, FastAPI
from fastapi.routing import APIRoute

from ...domain.rights import permission_of
from .deps import authenticate
from .errors import ACCOUNT_ERRORS, CALLER_ERRORS, RECORD_ERRORS
from .routes import (
    accounts,
    audit,
    discovery,
    health,
    mailbox,
    messages,
    oauth,
    status,
    users,
    webhooks,
)

PREFIX = "/v1"


def install(app: FastAPI) -> None:
    """Mount every router, each with the errors its routes can answer.

    Every ``/v1`` route gets its right from the catalogue as ``x-permission``.
    A route missing from the catalogue stops the app from starting.
    """
    app.include_router(health.router)
    # Every /v1 route authenticates, even one that does not use the caller.
    protected = [Depends(authenticate)]
    for router, errors in (
        (users.caller_router, CALLER_ERRORS),
        (users.router, RECORD_ERRORS),
        (accounts.router, ACCOUNT_ERRORS),
        (discovery.router, ACCOUNT_ERRORS),
        (oauth.router, ACCOUNT_ERRORS),
        (messages.router, ACCOUNT_ERRORS),
        (mailbox.router, ACCOUNT_ERRORS),
        (webhooks.router, RECORD_ERRORS),
        (audit.router, RECORD_ERRORS),
        (status.router, CALLER_ERRORS),
    ):
        for route in router.routes:
            if isinstance(route, APIRoute):
                _declare_permission(route)
        app.include_router(
            router, prefix=PREFIX, dependencies=protected, responses=errors
        )


def _declare_permission(route: APIRoute) -> None:
    permission = permission_of(route.name)
    if permission is None:
        raise RuntimeError(
            f"route {route.name} has no entry in the permission catalogue"
        )
    route.openapi_extra = {**(route.openapi_extra or {}), "x-permission": permission}
