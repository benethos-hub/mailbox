"""The status of the service and the recovery key (docs/UI.md, 6.5)."""

from __future__ import annotations

from typing import Annotated

from fastapi import APIRouter, Form, Request
from fastapi.responses import HTMLResponse, Response

from ...services import Recovery, Status
from ..deps import Actor, Viewer
from ..forms import failing
from ..session import show_once, take_once
from ..templates import back, render

router = APIRouter()

RECOVERY_PAGE = "/ui/recovery-key"


@router.get("/status")
async def status(request: Request, caller: Viewer, status: Status) -> HTMLResponse:
    """Accounts, the sync worker and the caller's webhooks. Nothing is asked
    of a provider for it."""
    return render(
        request,
        "pages/status.html",
        page="status",
        service=status.status(caller),
        can_webhooks=caller.allows("list_webhooks"),
    )


@router.get("/recovery-key")
async def recovery_key(request: Request, caller: Viewer) -> HTMLResponse:
    caller.require("show_recovery_key")
    return render(
        request,
        "pages/recovery_key.html",
        page="recovery",
        key=take_once(request, "recovery_key"),
    )


@router.post("/recovery-key")
async def show_recovery_key(
    request: Request,
    caller: Actor,
    recovery: Recovery,
    password: Annotated[str, Form()] = "",
) -> Response:
    """The key after the password once more. Kept for the next page only,
    never in the URL."""
    with failing(RECOVERY_PAGE):
        key = await recovery.show(caller, password)
    show_once(request, "recovery_key", key)
    return back(request, RECOVERY_PAGE)
