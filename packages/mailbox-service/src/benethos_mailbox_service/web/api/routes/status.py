"""The status of the service: the sync worker and the accounts."""

from __future__ import annotations

from fastapi import APIRouter

from ...services import Status
from ..deps import Caller
from ..schemas import ServiceStatus

router = APIRouter(tags=["status"])


@router.get("/status")
async def get_status(caller: Caller, status: Status) -> ServiceStatus:
    """The sync worker and the accounts the caller may see the status of:
    how their last pass went and whether one needs a look. Nothing is
    asked of a provider, so it suits a monitor. Kept in memory: empty
    again after a restart. The caller's failing webhooks are
    `GET /v1/webhooks?failing=true`."""
    return ServiceStatus.of(status.status(caller))
