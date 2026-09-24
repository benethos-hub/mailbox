"""The start page: who is signed in, its accounts and what it may do."""

from __future__ import annotations

from fastapi import APIRouter, Request
from fastapi.responses import HTMLResponse

from ...domain import permissions
from ...domain.users import UserService
from .deps import Viewer
from .templates import render

router = APIRouter()


@router.get("")
async def home(request: Request, caller: Viewer) -> HTMLResponse:
    users: UserService = request.app.state.users
    rights = users.me(caller)
    groups = {
        account.id: sorted(
            {
                group
                for op in account.operations
                if (group := permissions.GROUP_OF.get(op)) is not None
            }
        )
        for account in rights.accounts
    }
    return render(request, "pages/home.html", page="home", rights=rights, groups=groups)
