"""The audit of sends: who sent from which account to whom, never content."""

from __future__ import annotations

from fastapi import APIRouter, Request
from fastapi.responses import HTMLResponse

from ....domain.access import Access
from ...services import Accounts, Mailbox, get_users
from ..deps import Viewer, account_of
from ..templates import PAGE_SIZE, page_links, render

router = APIRouter()
# Across accounts: the latest of each, merged.
LATEST = 20


def _user_names(request: Request, caller: Access) -> dict[str, str]:
    """Names of the users who sent, where the caller may see users."""
    names = {caller.user_id: caller.name}
    if caller.allows("list_users"):
        users = get_users(request)
        names.update({user.id: user.name for user in users.list_users(caller)})
    return names


@router.get("/sends")
async def all_sends(
    request: Request, caller: Viewer, mailbox: Mailbox, accounts: Accounts
) -> HTMLResponse:
    """The latest sends of every account the caller may audit."""
    audited = accounts.list(caller, may="list_sends")
    records = mailbox.list_all_sends(caller, per_account=LATEST, limit=PAGE_SIZE)
    return render(
        request,
        "pages/sends.html",
        page="sends",
        account=None,
        accounts=audited,
        emails={account.id: account.email for account in audited},
        records=records,
        names=_user_names(request, caller),
        pages=(None, None),
    )


@router.get("/accounts/{account_id}/sends")
async def account_sends(
    request: Request, caller: Viewer, account_id: str, mailbox: Mailbox
) -> HTMLResponse:
    account = account_of(request, caller, account_id)
    cursor = request.query_params.get("cursor")
    page = mailbox.list_sends(caller, account_id, limit=PAGE_SIZE, cursor=cursor)
    return render(
        request,
        "pages/sends.html",
        page="sends",
        account=account,
        accounts=[],
        emails={account.id: account.email},
        records=page.items,
        names=_user_names(request, caller),
        pages=page_links(request, page.next_cursor),
    )
