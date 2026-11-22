"""The figures of the service for Prometheus."""

from __future__ import annotations

from fastapi import APIRouter, Request, Response

from .... import __version__
from ....errors import NotFoundError
from ...services import Status
from ...state import app_settings
from ..deps import Caller
from ..exposition import CONTENT_TYPE, exposition

router = APIRouter(tags=["status"])


@router.get(
    "/metrics",
    response_class=Response,
    responses={
        200: {"content": {"text/plain": {}}, "description": "Prometheus text format"}
    },
)
async def get_metrics(request: Request, caller: Caller, status: Status) -> Response:
    """The sync worker, every account and the webhooks as figures for
    Prometheus, in its text format. Needs the right `get_metrics` of the
    service, and shows every account, whatever the caller's grants reach.
    An account is named by its id, its provider and its status, never by
    its address, and no text of an error goes out. Nothing is asked of a
    provider. Kept in memory: the figures start again after a restart.
    Answers `404` while `MAILBOX_SERVICE_METRICS` is off."""
    if not app_settings(request.app).metrics:
        raise NotFoundError("metrics are switched off")
    body = exposition(status.figures(caller), __version__)
    return Response(content=body, media_type=CONTENT_TYPE)
