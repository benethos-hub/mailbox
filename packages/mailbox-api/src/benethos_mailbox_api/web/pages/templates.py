"""Templates of the configuration UI: the Jinja2 environment, its filters and
``render``. The only module that imports ``jinja2``.

Formatting happens in the filters here, never in a template. A missing
value shows as ``—``.
"""

from __future__ import annotations

from datetime import datetime
from pathlib import Path
from typing import Any
from urllib.parse import quote, urlencode

import jinja2
from fastapi import Request
from fastapi.responses import HTMLResponse, RedirectResponse, Response
from fastapi.templating import Jinja2Templates

from ... import __version__

HERE = Path(__file__).resolve().parent
TEMPLATE_DIR = HERE / "templates"
STATIC_DIR = HERE / "static"
MISSING = "—"

templates = Jinja2Templates(directory=str(TEMPLATE_DIR))
# A typo in a template raises instead of rendering an empty cell.
templates.env.undefined = jinja2.StrictUndefined


def when(value: datetime | str | None) -> str:
    """Local date and time to the minute."""
    if value is None or value == "":
        return MISSING
    if isinstance(value, str):
        value = datetime.fromisoformat(value)
    return value.astimezone().strftime("%Y-%m-%d %H:%M")


def size(value: int | None) -> str:
    if value is None:
        return MISSING
    for unit in ("B", "KB", "MB"):
        if value < 1024 or unit == "MB":
            return f"{value:.0f} {unit}" if unit == "B" else f"{value:.1f} {unit}"
        value = value / 1024  # type: ignore[assignment]
    return MISSING  # pragma: no cover


def address(value: Any) -> str:
    """``Name <email>``, from a model or a dict."""
    if value is None:
        return MISSING
    name = (
        getattr(value, "name", None)
        if not isinstance(value, dict)
        else value.get("name")
    )
    email = (
        getattr(value, "email", None)
        if not isinstance(value, dict)
        else value.get("email")
    )
    return f"{name} <{email}>" if name else str(email or MISSING)


def addresses(values: Any) -> str:
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
