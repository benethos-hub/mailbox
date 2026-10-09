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
from urllib.parse import quote, urlencode, urlsplit

import jinja2
from fastapi import Request
from fastapi.responses import HTMLResponse, RedirectResponse, Response
from fastapi.templating import Jinja2Templates

from benethos_mailbox_common.logs import log_time

from ... import __version__
from ...common.clock import utc_now
from ...common.text import plural
from ...common.urls import path_and_query
from ...data.models import Address
from ...domain.rights import Access
from ...domain.system import Attention
from ...errors import MailboxServiceError
from ..services import get_status
from .navigation import navigation, own_page
from .session import PATH, SignInRequiredError, found_for, show_once, store_of

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


def ago(value: datetime | None) -> str:
    """A time in a list: under a day ago "3 minutes ago", older as
    ``when``. A time to come is ``when`` as well."""
    if value is None:
        return MISSING
    seconds = (utc_now() - value).total_seconds()
    if not 0 <= seconds < _DAY:
        return when(value)
    if seconds < _MINUTE:
        return "just now"
    if seconds < _HOUR:
        return f"{plural(int(seconds // _MINUTE), 'minute')} ago"
    return f"{plural(int(seconds // _HOUR), 'hour')} ago"


_MINUTE, _HOUR, _DAY = 60, 3600, 86400


def past(value: datetime | None) -> bool:
    """Whether a time has come: an expired grant, for example."""
    return value is not None and value <= utc_now()


def size(value: int | None) -> str:
    if value is None:
        return MISSING
    number = float(value)
    for unit in ("B", "KB", "MB"):
        if number < 1024 or unit == "MB":
            return f"{number:.0f} {unit}" if unit == "B" else f"{number:.1f} {unit}"
        number /= 1024
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


def own_keywords(values: Iterable[str]) -> list[str]:
    """The keywords a person sets. Those starting with ``$``, such as
    ``$answered``, belong to the mail protocol (docs/UI.md, 4.4)."""
    return [value for value in values if not value.startswith("$")]


# Who a person signs in at, by the kind of account.
_SIGNS_IN_AT = {"gmail": "Google", "microsoft": "Microsoft"}


def signs_in_at(provider: str) -> str:
    """The company a person signs in at for an account of ``provider``:
    Google for Gmail."""
    return _SIGNS_IN_AT.get(provider, provider.capitalize())


def segment(value: str) -> str:
    """Free text as one part of a path, e.g. a role name."""
    return quote(str(value), safe="")


templates.env.filters.update(
    when=when,
    ago=ago,
    past=past,
    moment=log_time,
    size=size,
    address=address,
    addresses=addresses,
    or_missing=or_missing,
    own_keywords=own_keywords,
    segment=segment,
    signs_in_at=signs_in_at,
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
    entries the caller may open and their dots, the session's CSRF token,
    who is signed in, and the message the form before left in the
    session."""
    found = found_for(request)
    session = found.session if found is not None else None
    access = found.access if found is not None else None
    attention = _attention(request, access) if access is not None else None
    context.update(
        page=page,
        csrf=session.csrf if session is not None else "",
        me=access,
        nav=navigation(access, attention) if access is not None else [],
        own_page=own_page(access) if access is not None else None,
        # For the account menu: whether a code follows the password.
        factor_on=session is not None and session.factor is not None,
    )
    for key in ("msg", "err"):
        kept = (
            store_of(request).take_once(session, key) if session is not None else None
        )
        if context.get(key) is None:
            context[key] = kept
    response: HTMLResponse = templates.TemplateResponse(
        request, template, context, status_code=status_code
    )
    return response


def _attention(request: Request, access: Access) -> Attention | None:
    """The dots of the sidebar, None when they cannot be told: a page
    and the error page still open without them."""
    try:
        return get_status(request).attention(access)
    except MailboxServiceError:
        return None


def is_htmx(request: Request) -> bool:
    return request.headers.get("HX-Request") == "true"


def back(
    request: Request,
    path: str,
    message: str | None = None,
    error: str | None = None,
) -> Response:
    """Post/Redirect/Get: the browser lands on a GET, a reload repeats
    nothing. The message waits in the session for the next page, never in
    the URL, so a link cannot put words into the UI."""
    try:
        for key, value in (("msg", message), ("err", error)):
            if value:
                show_once(request, key, value)
    except SignInRequiredError:
        pass  # signed out meanwhile: the sign-in page says so
    return RedirectResponse(path, status_code=303)


def local_path(value: str | None, fallback: str) -> str:
    """Where to go after a form: a page of this UI, never another site."""
    parts = urlsplit(value or "")
    inside = parts.path == PATH or parts.path.startswith(PATH + "/")
    if parts.scheme or parts.netloc or not inside:
        return fallback
    return path_and_query(value or "")


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
