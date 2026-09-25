"""The start page: who is signed in, its accounts and what it may do."""

from __future__ import annotations

from fastapi import APIRouter, Request
from fastapi.responses import HTMLResponse

from ...services import Users
from ..deps import Viewer
from ..effective import view_of
from ..templates import render

router = APIRouter()


@router.get("")
async def home(request: Request, caller: Viewer, users: Users) -> HTMLResponse:
    """The rights per account as the user page shows them: whole groups
    as groups, the rest as single operations."""
    rights = users.me(caller)
    view = view_of(rights)
    rows = dict(zip((a.id for a in rights.accounts), view.accounts, strict=True))
    return render(request, "pages/home.html", page="home", rights=rights, rows=rows)
