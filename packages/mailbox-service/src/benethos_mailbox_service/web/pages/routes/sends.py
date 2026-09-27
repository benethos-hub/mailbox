"""The audit of sends: who sent from which account to whom, never content.
One list for every account the caller may audit, narrowed by the filter
bar, an account among its filters."""

from __future__ import annotations

from datetime import UTC, date, datetime, time

from fastapi import APIRouter, Request
from fastapi.responses import HTMLResponse
from pydantic import ValidationError

from ....data.models import SendFilter
from ....domain.access import Access
from ...services import Accounts, Mailbox, get_users
from ..deps import Viewer, emails_of
from ..filters import Field, FilterBar, filter_bar
from ..forms import first_problem
from ..templates import PAGE_SIZE, page_links, render

router = APIRouter()

OUTCOMES = [("sent", "sent"), ("denied", "denied"), ("failed", "failed")]


def _user_names(request: Request, caller: Access) -> dict[str, str]:
    """Names of the users who sent, where the caller may see users."""
    names = {caller.user_id: caller.name}
    if caller.allows("list_users"):
        users = get_users(request)
        names.update({user.id: user.name for user in users.list_users(caller)})
    return names


def _day(value: str) -> datetime | None:
    """The start of a day, in UTC."""
    return datetime.combine(date.fromisoformat(value), time(), UTC) if value else None


def _filter(bar: FilterBar) -> SendFilter | None:
    """What the bar asks for. Raises ``ValueError`` for a value that is no
    filter."""
    wanted = {
        "user_id": bar.value("who") or None,
        "outcome": bar.value("outcome") or None,
        "recipient": bar.value("to") or None,
        "after": _day(bar.value("after")),
        "before": _day(bar.value("before")),
    }
    if not any(value is not None for value in wanted.values()):
        return None
    try:
        return SendFilter.model_validate(wanted)
    except ValidationError as exc:
        raise ValueError(first_problem(exc)) from None


@router.get("/sends")
async def sends(
    request: Request, caller: Viewer, mailbox: Mailbox, accounts: Accounts
) -> HTMLResponse:
    audited = accounts.list(caller, may="list_sends")
    names = _user_names(request, caller)
    bar = filter_bar(
        request,
        (
            Field("account", "Account", "select", [(a.id, a.email) for a in audited]),
            Field("who", "Who", "select", sorted(names.items(), key=lambda n: n[1])),
            Field("outcome", "Outcome", "select", OUTCOMES),
            Field("after", "From day", "date"),
            Field("before", "Before day", "date"),
        ),
        search=Field("to", "Recipient"),
    )
    problem = ""
    try:
        matching = _filter(bar)
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
