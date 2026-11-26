"""Whether the service answers: for a health check of a container, a
proxy or a monitor, without a token and without a limit."""

from __future__ import annotations

from typing import Any

from fastapi import APIRouter

from .... import __version__
from ...services import Status
from ..schemas import ErrorResponse

router = APIRouter(tags=["health"])

_AWAY: dict[int | str, dict[str, Any]] = {
    503: {
        "model": ErrorResponse,
        "description": "The service cannot reach its database for now "
        "(`service_unavailable`), see Retry-After",
    }
}


@router.get("/health", responses=_AWAY)
async def health(status: Status) -> dict[str, str]:
    """`ok` and the version while the service can answer. While its
    database is away, 503: the state is kept, the database is not asked."""
    status.reachable()
    return {"status": "ok", "version": __version__}
