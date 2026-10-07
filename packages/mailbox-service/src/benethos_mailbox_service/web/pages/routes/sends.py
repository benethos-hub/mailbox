"""The audit of sends: who sent from which account to whom, never content.
One list for every account the caller may audit, narrowed by the filter
bar, an account among its filters."""

from __future__ import annotations

from fastapi import APIRouter, Request
from fastapi.responses import HTMLResponse

from ....data.models import SendFilter
from ...services import Accounts, Mailbox
from ..deps import Viewer, emails_of
from ..filters import Field, filter_bar, records_filter, user_names
from ..templates import PAGE_SIZE, page_links, render

router = APIRouter()

OUTCOMES = [("sent", "sent"), ("denied", "denied"), ("failed", "failed")]


@router.get("/sends")
async def sends(
    request: Request, caller: Viewer, mailbox: Mailbox, accounts: Accounts
) -> HTMLResponse:
    audited = accounts.list(caller, may="list_sends")
    names = user_names(request, caller)
    bar = filter_bar(
        request,
        (
            Field("account", "Account", "select", [(a.id, a.email) for a in audited]),
            Field("user", "Who", "select", sorted(names.items(), key=lambda n: n[1])),
            Field("outcome", "Outcome", "select", OUTCOMES),
            Field("after", "From day", "date"),
            Field("before", "Before day", "date"),
        ),
        search=Field("recipient", "Recipient"),
    )
    problem = ""
    try:
        matching = records_filter(SendFilter, bar, "outcome", "recipient")
    except ValueError as exc:
        matching, problem = None, f"Filter: {exc}"
    account_id = bar.value("account")
    cursor = request.query_params.get("cursor")
    if account_id:
        page = mailbox.outgoing.list_sends(
            caller, account_id, limit=PAGE_SIZE, cursor=cursor, matching=matching
        )
    else:
        page = mailbox.outgoing.list_all_sends(
            caller, limit=PAGE_SIZE, cursor=cursor, matching=matching
        )
    return render(
        request,
        "pages/sends.html",
        page="sends",
        bar=bar,
        problem=problem,
        one_account=bool(account_id),
        emails=emails_of(audited),
        records=page.items,
        names=names,
        pages=page_links(request, page.next_cursor),
    )
