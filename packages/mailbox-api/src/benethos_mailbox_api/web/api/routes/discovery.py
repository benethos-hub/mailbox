from __future__ import annotations

from fastapi import APIRouter

from ....data.models import Discovery
from ..deps import Caller, Discoverer
from ..schemas import DiscoveryRequest, ErrorResponse

router = APIRouter(prefix="/discovery", tags=["discovery"])


@router.post(
    "",
    responses={
        400: {"model": ErrorResponse, "description": "Not a valid email address"},
        429: {
            "model": ErrorResponse,
            "description": "Too many discoveries, see Retry-After",
        },
    },
)
async def discover_account(
    data: DiscoveryRequest, caller: Caller, discovery: Discoverer
) -> Discovery:
    """Ways to connect an address, best first. Looks up only, sends no
    credential. POST so the address stays out of access logs."""
    return await discovery.discover(caller, data.email)
