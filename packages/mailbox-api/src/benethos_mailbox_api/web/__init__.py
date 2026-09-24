"""Web layer: HTTP and nothing else.

Checks input, calls the domain, answers. FastAPI is imported here and
nowhere else. ``routes`` holds one router per resource, ``schemas`` the
shapes that exist only at the HTTP boundary, ``errors`` the mapping from
domain errors to status codes, ``deps`` authentication and the services a
route needs. May import ``domain`` and ``data``.
"""

from __future__ import annotations

from fastapi import Depends, FastAPI

from .deps import require_api_key
from .errors import DOCUMENTED_ERRORS
from .routes import accounts, health, mailbox

API_PREFIX = "/v1"


def include_routes(app: FastAPI) -> None:
    """Mount every router: ``/health`` open, everything else under ``/v1``."""
    app.include_router(health.router)
    protected = [Depends(require_api_key)]
    for router in (accounts.router, mailbox.router):
        app.include_router(
            router,
            prefix=API_PREFIX,
            dependencies=protected,
            responses=DOCUMENTED_ERRORS,
        )
