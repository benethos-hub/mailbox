"""The audit of administration (docs/AUDIT.md): who signed in and who
changed users, tokens, roles, accounts and webhooks. One list, narrowed
by the filter bar."""

from __future__ import annotations

from datetime import UTC, date, datetime, time

from fastapi import APIRouter, Request
from fastapi.responses import HTMLResponse

from ....data.models import ActivityFilter
from ....domain.activity import audited
from ....domain.rights import Access
from ...services import Activities, get_users
from ..deps import Viewer, if_allowed
from ..filters import Field, FilterBar, filter_bar
from ..forms import model_of
from ..templates import PAGE_SIZE, page_links, render

router = APIRouter()

OUTCOMES = {"done": "ok", "refused": "warn", "failed": "bad"}


def _user_names(request: Request, caller: Access) -> dict[str, str]:
    """Names of the users, where the caller may see users."""
    listed: dict[str, str] = if_allowed(
        caller,
        "list_users",
        lambda: {u.id: u.name for u in get_users(request).list_users(caller)},
        {},
    )
    return {caller.user_id: caller.name, **listed}


def activity_choices() -> list[tuple[str, str]]:
    """Each area the audit keeps, then each of its names."""
    names = audited()
    areas = sorted({name.partition(".")[0] for name in names})
    return [(area, f"{area}, every one") for area in areas] + [(n, n) for n in names]


def _day(value: str) -> datetime | None:
    """The start of a day, in UTC."""
    return datetime.combine(date.fromisoformat(value), time(), UTC) if value else None


def _filter(bar: FilterBar) -> ActivityFilter | None:
    """What the bar asks for. Raises ``FormError``, a ``ValueError``, for
    a value that is no filter."""
    wanted = {
        "user_id": bar.value("user") or None,
        "activity": bar.value("activity") or None,
        "record": bar.value("record") or None,
        "after": _day(bar.value("after")),
        "before": _day(bar.value("before")),
    }
    if not any(value is not None for value in wanted.values()):
        return None
    return model_of(ActivityFilter, wanted)


@router.get("/audit")
async def audit_page(
    request: Request, caller: Viewer, audit: Activities
) -> HTMLResponse:
    names = _user_names(request, caller)
    bar = filter_bar(
        request,
        (
            Field("user", "Who", "select", sorted(names.items(), key=lambda n: n[1])),
            Field("activity", "Activity", "select", activity_choices()),
            Field("after", "From day", "date"),
            Field("before", "Before day", "date"),
        ),
        search=Field("record", "Record id"),
    )
    problem = ""
    try:
        matching = _filter(bar)
    except ValueError as exc:
        matching, problem = None, f"Filter: {exc}"
    page = audit.list_activity(
        caller,
        limit=PAGE_SIZE,
        cursor=request.query_params.get("cursor"),
        matching=matching,
    )
    return render(
        request,
        "pages/audit.html",
        page="audit",
        bar=bar,
        problem=problem,
        records=page.items,
        days=audit.days,
        outcomes=OUTCOMES,
        user_pages=caller.allows("get_user"),
        pages=page_links(request, page.next_cursor),
    )
