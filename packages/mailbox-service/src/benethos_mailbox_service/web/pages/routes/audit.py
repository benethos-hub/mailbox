"""The audit of administration (docs/AUDIT.md): who signed in and who
changed users, tokens, roles, accounts and webhooks. One list, narrowed
by the filter bar."""

from __future__ import annotations

from fastapi import APIRouter, Request
from fastapi.responses import HTMLResponse

from ....data.models import ActivityFilter
from ....domain.activity import audited
from ...services import Activities
from ..deps import Viewer
from ..filters import Field, filter_bar, records_filter, user_names
from ..templates import PAGE_SIZE, page_links, render

router = APIRouter()

OUTCOMES = {"done": "ok", "refused": "warn", "failed": "bad"}


def activity_choices() -> list[tuple[str, str]]:
    """Each area the audit keeps, then each of its names."""
    names = audited()
    areas = sorted({name.partition(".")[0] for name in names})
    return [(area, f"{area}, every one") for area in areas] + [(n, n) for n in names]


@router.get("/audit")
async def audit_page(
    request: Request, caller: Viewer, audit: Activities
) -> HTMLResponse:
    names = user_names(request, caller)
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
        matching = records_filter(ActivityFilter, bar, "activity", "record")
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
