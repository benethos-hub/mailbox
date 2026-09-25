"""Templates of the configuration UI: the Jinja2 environment, its filters and
``render``. The only module that imports ``jinja2``.

Formatting happens in the filters here, never in a template. A missing
value shows as ``—``.
"""

from __future__ import annotations

from collections.abc import Iterable
from datetime import datetime
from pathlib import Path
from typing import Any
from urllib.parse import parse_qsl, quote, urlencode, urlsplit

import jinja2
from fastapi import Request
from fastapi.responses import HTMLResponse, RedirectResponse, Response
from fastapi.templating import Jinja2Templates

from ... import __version__
from ...data.models import Address
from .session import PATH

HERE = Path(__file__).resolve().parent
TEMPLATE_DIR = HERE / "templates"
STATIC_DIR = HERE / "static"
MISSING = "—"
# Items per page of a list.
PAGE_SIZE = 50

templates = Jinja2Templates(directory=str(TEMPLATE_DIR))
# A typo in a template raises instead of rendering an empty cell.
templates.env.undefined = jinja2.StrictUndefined


def when(value: datetime | None) -> str:
    """Local date and time to the minute."""
    if value is None:
        return MISSING
    return value.astimezone().strftime("%Y-%m-%d %H:%M")


def size(value: int | None) -> str:
    if value is None:
        return MISSING
    for unit in ("B", "KB", "MB"):
        if value < 1024 or unit == "MB":
            return f"{value:.0f} {unit}" if unit == "B" else f"{value:.1f} {unit}"
        value = value / 1024  # type: ignore[assignment]
    return MISSING  # pragma: no cover


def address(value: Address | None) -> str:
    """``Name <email>``, or the email alone."""
    if value is None:
        return MISSING
    return f"{value.name} <{value.email}>" if value.name else value.email


def addresses(values: Iterable[Address] | None) -> str:
    return ", ".join(address(v) for v in values or []) or MISSING


def or_missing(value: Any) -> Any:
    return MISSING if value is None or value == "" else value


def segment(value: str) -> str:
    """Free text as one part of a path, e.g. a role name."""
    return quote(str(value), safe="")


templates.env.filters.update(
    when=when,
    size=size,
    address=address,
    addresses=addresses,
    or_missing=or_missing,
    segment=segment,
)
templates.env.globals.update(APP_NAME="Mailbox", VERSION=__version__)


def render(
    request: Request,
    template: str,
    *,
    page: str,
    status_code: int = 200,
    **context: Any,
) -> HTMLResponse:
    """A page, with what the layout needs: the active navigation entry, the
    session's CSRF token and who is signed in."""
    session = getattr(request.state, "ui_session", None)
    access = getattr(request.state, "access", None)
    context.update(
        page=page,
        csrf=session.csrf if session is not None else "",
        me=access,
    )
    response: HTMLResponse = templates.TemplateResponse(
        request, template, context, status_code=status_code
    )
    return response


def is_htmx(request: Request) -> bool:
    return request.headers.get("HX-Request") == "true"


def back(path: str, message: str | None = None, error: str | None = None) -> Response:
    """Post/Redirect/Get: the browser lands on a GET, a reload repeats
    nothing. The message travels in the query and is gone on the next page."""
    query = {k: v for k, v in (("msg", message), ("err", error)) if v}
    separator = "&" if "?" in path else "?"
    url = f"{path}{separator}{urlencode(query)}" if query else path
    return RedirectResponse(url, status_code=303)


def local_path(value: str | None, fallback: str) -> str:
    """Where to go after a form: a page of this UI, never another site.
    A message the earlier redirect carried is dropped. The next replaces it."""
    parts = urlsplit(value or "")
    inside = parts.path == PATH or parts.path.startswith(PATH + "/")
    if parts.scheme or parts.netloc or not inside:
        return fallback
    query = urlencode(
        [(k, v) for k, v in parse_qsl(parts.query) if k not in ("msg", "err")]
    )
    return f"{parts.path}?{query}" if query else parts.path


def page_links(request: Request, cursor: str | None) -> tuple[str | None, str | None]:
    """Links to the next page (this query with the next cursor) and, from a
    later page, back to the first."""
    query = [(k, v) for k, v in request.query_params.multi_items() if k != "cursor"]
    here = request.url.path
    more = f"{here}?{urlencode([*query, ('cursor', cursor)])}" if cursor else None
    first = None
    if "cursor" in request.query_params:
        first = f"{here}?{urlencode(query)}" if query else here
    return more, first
