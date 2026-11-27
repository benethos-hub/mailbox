"""The app of the cockpit: its pages, the sign-in with its secret, and
the headers on every answer.

Each page reads the state files anew. A page never takes a word of its
address into its text: a notice is chosen by a key from a fixed list,
and an instance by a name among the files found.
"""

from __future__ import annotations

from collections.abc import Callable
from dataclasses import dataclass, field
from datetime import datetime
from pathlib import Path
from typing import Annotated, Any

from fastapi import Depends, FastAPI, Form, HTTPException, Request
from fastapi.exceptions import RequestValidationError
from fastapi.responses import HTMLResponse, RedirectResponse, Response
from fastapi.staticfiles import StaticFiles

from benethos_mailbox_common.values import secret

from ..records import MessageRef
from ..store import STATES
from . import security, sources, views
from .templates import STATIC_DIR, render

__all__ = ["Cockpit", "make_app"]

STATIC = "/static"
# The newest results an instance shows, and the most it shows.
LIMIT = 50
MAX_LIMIT = 200
SEE_OTHER = 303

# What the sign-in page may say, by the key in its address.
NOTICES = {
    "wrong": "That secret is not the one of this cockpit.",
    "expired": "The form was too old. Sign in again.",
    "out": "You are signed out.",
}

# The title and the text of an error page, by its status.
ERRORS = {
    400: ("Not valid", "This address asks for something the cockpit cannot show."),
    403: ("Refused", "This form is no longer valid. Reload the page and try again."),
    404: ("Not found", "There is nothing at this address."),
    405: ("Not allowed", "This address does not take that kind of request."),
}


class _SignInRequiredError(Exception):
    """No session: the page sends the browser to the sign-in."""


@dataclass
class Cockpit:
    """What the pages read: the data folder, the secret to sign in with,
    the mailbox service when it is set, and the clock."""

    data_dir: Path
    secret: str
    mailbox: views.MailboxFactory | None
    now: Callable[[], datetime]
    sessions: security.Sessions = field(default_factory=security.Sessions)
    throttle: security.Throttle = field(default_factory=security.Throttle)


def _cockpit(request: Request) -> Cockpit:
    found: Cockpit = request.app.state.cockpit
    return found


def _signed_in(request: Request) -> security.Session:
    cockpit = _cockpit(request)
    found = cockpit.sessions.get(request.cookies.get(security.COOKIE), cockpit.now())
    if found is None:
        raise _SignInRequiredError
    return found


Viewer = Annotated[security.Session, Depends(_signed_in)]


def _cookie(request: Request, response: Response, name: str, value: str) -> None:
    response.set_cookie(
        name,
        value,
        httponly=True,
        samesite="strict",
        path="/",
        secure=request.url.scheme == "https",
    )


def _to(path: str) -> RedirectResponse:
    return RedirectResponse(path, status_code=SEE_OTHER)


def _source(request: Request) -> str:
    return request.client.host if request.client is not None else ""


def _file(request: Request, name: str) -> sources.StateFile:
    found = sources.find(_cockpit(request).data_dir, name)
    if found is None:
        raise HTTPException(404)
    return found


async def overview(request: Request, session: Viewer) -> HTMLResponse:
    cockpit = _cockpit(request)
    now = cockpit.now()
    rows = [views.row(file, now) for file in sources.found(cockpit.data_dir)]
    return render(request, "pages/overview.html", rows=rows, session=session)


async def instance(
    request: Request,
    session: Viewer,
    name: str,
    limit: int = LIMIT,
    state: str | None = None,
) -> HTMLResponse:
    if state is not None and state not in STATES:
        raise HTTPException(400)
    cockpit = _cockpit(request)
    file = _file(request, name)
    row = views.row(file, cockpit.now())
    results = []
    if row.problem is None:
        shown = min(max(limit, 1), MAX_LIMIT)
        results = await views.results(file, cockpit.mailbox, limit=shown, state=state)
    return render(
        request,
        "pages/instance.html",
        row=row,
        results=results,
        state=state,
        states=STATES,
        named=cockpit.mailbox is not None,
        session=session,
    )


async def message(
    request: Request, session: Viewer, name: str, account_id: str, message_id: str
) -> HTMLResponse:
    cockpit = _cockpit(request)
    file = _file(request, name)
    row = views.row(file, cockpit.now())
    if row.problem is not None:
        raise HTTPException(404)
    ref = MessageRef(account_id=account_id, message_id=message_id)
    found = await views.message(file, ref, cockpit.mailbox)
    if found is None:
        raise HTTPException(404)
    return render(
        request,
        "pages/message.html",
        row=row,
        detail=found,
        named=cockpit.mailbox is not None,
        session=session,
    )


async def login_page(request: Request, notice: str | None = None) -> Response:
    cockpit = _cockpit(request)
    if cockpit.sessions.get(request.cookies.get(security.COOKIE), cockpit.now()):
        return _to("/")
    return _login(request, NOTICES.get(notice or ""))


def _login(request: Request, notice: str | None, status_code: int = 200) -> Response:
    nonce = secret.token(secret.SHORT)
    response = render(
        request, "pages/login.html", status_code=status_code, nonce=nonce, notice=notice
    )
    _cookie(request, response, security.LOGIN_COOKIE, nonce)
    return response


async def login(
    request: Request,
    given: Annotated[str, Form(alias="secret")] = "",
    nonce: Annotated[str, Form()] = "",
) -> Response:
    cockpit = _cockpit(request)
    now, source = cockpit.now(), _source(request)
    wait = cockpit.throttle.wait(source, now)
    if wait:
        minutes = max(1, -(-wait // 60))
        notice = f"Too many failed attempts. Try again in {minutes} minutes."
        response = _login(request, notice, status_code=429)
        response.headers["retry-after"] = str(wait)
        return response
    expected = request.cookies.get(security.LOGIN_COOKIE) or ""
    if not expected or not secret.same(nonce, expected):
        return _to("/login?notice=expired")
    if not secret.same(given, cockpit.secret):
        cockpit.throttle.failed(source, now)
        return _to("/login?notice=wrong")
    cockpit.throttle.succeeded(source)
    session = cockpit.sessions.start(now)
    response = _to("/")
    _cookie(request, response, security.COOKIE, session.id)
    response.delete_cookie(security.LOGIN_COOKIE, path="/")
    return response


async def logout(
    request: Request, session: Viewer, token: Annotated[str, Form()] = ""
) -> Response:
    if not secret.same(token, session.token):
        raise HTTPException(403)
    _cockpit(request).sessions.end(session.id)
    response = _to("/login?notice=out")
    response.delete_cookie(security.COOKIE, path="/")
    return response


def _error(request: Request, status: int) -> HTMLResponse:
    title, text = ERRORS.get(status, ("Error", "The cockpit could not answer."))
    return render(
        request, "pages/error.html", status_code=status, title=title, text=text
    )


async def _http_error(request: Request, exc: Exception) -> Response:
    """An error page for every status of :data:`ERRORS`, also for an
    address no route takes, which the framework below FastAPI answers."""
    return _error(request, int(getattr(exc, "status_code", 500)))


async def _invalid(request: Request, exc: Exception) -> Response:
    return _error(request, 400)


async def _sign_in(request: Request, exc: Exception) -> Response:
    return _to("/login")


def make_app(cockpit: Cockpit) -> FastAPI:
    """The app of the cockpit over ``cockpit``."""
    app = FastAPI(docs_url=None, redoc_url=None, openapi_url=None)
    app.state.cockpit = cockpit
    app.mount(STATIC, StaticFiles(directory=STATIC_DIR), name="static")
    page: dict[str, Any] = {"response_class": HTMLResponse}
    app.get("/", **page)(overview)
    app.get("/agents/{name}", **page)(instance)
    app.get("/agents/{name}/messages/{account_id}/{message_id:path}", **page)(message)
    app.get("/login")(login_page)
    app.post("/login")(login)
    app.post("/logout")(logout)
    for status in ERRORS:
        app.add_exception_handler(status, _http_error)
    app.add_exception_handler(RequestValidationError, _invalid)
    app.add_exception_handler(_SignInRequiredError, _sign_in)

    @app.middleware("http")
    async def _guarded(
        request: Request, call_next: Callable[[Request], Any]
    ) -> Response:
        response: Response = await call_next(request)
        static = request.url.path.startswith(f"{STATIC}/")
        response.headers.update(security.headers(static))
        return response

    return app
