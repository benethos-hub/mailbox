"""The recovery key and the service log (docs/UI.md, 6.5). The status
of the service is on the overview and the accounts list."""

from __future__ import annotations

from typing import Annotated

from fastapi import APIRouter, Form, Request
from fastapi.responses import HTMLResponse, Response

from ....domain.system import LEVELS
from ...services import Log, Recovery
from ..deps import Actor, Viewer
from ..filters import Field, filter_bar
from ..forms import failing
from ..session import show_once, take_once
from ..templates import PAGE_SIZE, back, page_links, render

router = APIRouter()

RECOVERY_PAGE = "/ui/recovery-key"
LOG_LEVELS = [(name, name) for name in LEVELS]


@router.get("/log")
async def service_log(request: Request, caller: Viewer, log: Log) -> HTMLResponse:
    """The newest lines of this service's log, since its start."""
    bar = filter_bar(
        request,
        (Field("level", "At least", "select", LOG_LEVELS),),
        search=Field("text", "Search"),
    )
    lines = log.lines(
        caller,
        text=bar.value("text") or None,
        level=bar.value("level") or None,
        limit=PAGE_SIZE,
        cursor=request.query_params.get("cursor"),
    )
    return render(
        request,
        "pages/log.html",
        page="log",
        bar=bar,
        lines=lines.items,
        pages=page_links(request, lines.next_cursor),
    )


@router.get("/recovery-key")
async def recovery_key(
    request: Request, caller: Viewer, recovery: Recovery
) -> HTMLResponse:
    caller.require("show_recovery_key")
    return render(
        request,
        "pages/recovery_key.html",
        page="recovery",
        key=take_once(request, "recovery_key"),
        needs_code=recovery.needs_code(caller),
    )


@router.post("/recovery-key")
async def show_recovery_key(
    request: Request,
    caller: Actor,
    recovery: Recovery,
    password: Annotated[str, Form()] = "",
    code: Annotated[str, Form()] = "",
) -> Response:
    """The key after the password once more, and a code with a second
    factor. Kept for the next page only, never in the URL."""
    with failing(RECOVERY_PAGE):
        key = await recovery.show(caller, password, code)
    show_once(request, "recovery_key", key)
    return back(request, RECOVERY_PAGE)
