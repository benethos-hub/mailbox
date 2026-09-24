"""The audit of sends: who sent from which account to whom, never content."""

from __future__ import annotations

from urllib.parse import urlencode

from fastapi import APIRouter, Request
from fastapi.responses import HTMLResponse

from ....data.models import SendRecord
from ....domain.access import Access
from ....domain.accounts import AccountService
from ....domain.mailbox import MailboxService
from ....domain.users import UserService
from ..deps import Viewer, account_of
from ..templates import render

router = APIRouter()

PAGE_SIZE = 50
# Across accounts: the latest of each, merged.
LATEST = 20


def _mailbox(request: Request) -> MailboxService:
    mailbox: MailboxService = request.app.state.mailbox
    return mailbox


def _user_names(request: Request, caller: Access) -> dict[str, str]:
    """Names of the users who sent, where the caller may see users."""
    names = {caller.user_id: caller.name}
    if caller.allows("list_users"):
        users: UserService = request.app.state.users
        names.update({user.id: user.name for user in users.list_users(caller)})
    return names


@router.get("/sends")
async def all_sends(request: Request, caller: Viewer) -> HTMLResponse:
    """The latest sends of every account the caller may audit."""
    accounts: AccountService = request.app.state.accounts
    audited = [
        account
        for account in accounts.list(caller)
        if caller.allows("list_sends", account.id)
    ]
    records: list[SendRecord] = []
    for account in audited:
        page = _mailbox(request).list_sends(
            caller, account.id, limit=LATEST, cursor=None
        )
        records.extend(page.items)
    records.sort(key=lambda record: (record.created_at, record.id), reverse=True)
    return render(
        request,
        "pages/sends.html",
        page="sends",
        account=None,
        accounts=audited,
        emails={account.id: account.email for account in audited},
        records=records[:PAGE_SIZE],
        names=_user_names(request, caller),
        pages=(None, None),
    )


@router.get("/accounts/{account_id}/sends")
async def account_sends(
    request: Request, caller: Viewer, account_id: str
) -> HTMLResponse:
    account = account_of(request, caller, account_id)
    cursor = request.query_params.get("cursor")
    page = _mailbox(request).list_sends(
        caller, account_id, limit=PAGE_SIZE, cursor=cursor
    )
    here = f"/ui/accounts/{account_id}/sends"
    return render(
        request,
        "pages/sends.html",
        page="sends",
        account=account,
        accounts=[],
        emails={account.id: account.email},
        records=page.items,
        names=_user_names(request, caller),
        pages=(
            f"{here}?{urlencode({'cursor': page.next_cursor})}"
            if page.next_cursor
            else None,
            here if cursor else None,
        ),
    )
