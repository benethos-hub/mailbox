"""The overview (docs/UI.md, section 5): who is signed in, its accounts,
and for those who may list accounts what needs attention."""

from __future__ import annotations

from dataclasses import dataclass

from fastapi import APIRouter, Request
from fastapi.responses import HTMLResponse

from ....domain.users import AccountRights
from ...services import Status, Users
from ..deps import Viewer
from ..effective import AccountRow, view_of
from ..navigation import mail_url
from ..session import session_of
from ..templates import render

router = APIRouter()


@dataclass(frozen=True)
class Row:
    """One of the caller's accounts, with where its links lead."""

    rights: AccountRights
    view: AccountRow
    page: str | None
    mail: str | None


@router.get("")
async def home(
    request: Request, caller: Viewer, users: Users, status: Status
) -> HTMLResponse:
    """The rights per account as the user page shows them: whole groups
    as groups, the rest as single operations."""
    rights = users.me(caller)
    view = view_of(rights)
    rows = [
        Row(
            rights=account,
            view=row,
            page=(
                f"/ui/accounts/{account.id}"
                if caller.allows("get_account", account.id)
                else None
            ),
            mail=(
                mail_url(account.id)
                if caller.allows("list_messages", account.id)
                else None
            ),
        )
        for account, row in zip(rights.accounts, view.accounts, strict=True)
    ]
    return render(
        request,
        "pages/home.html",
        page="home",
        rights=rights,
        view=view,
        rows=rows,
        anywhere=any(row.view.warnings for row in rows),
        previous_sign_in=session_of(request).previous_sign_in,
        service=status.status(caller) if caller.sees_status() else None,
    )
