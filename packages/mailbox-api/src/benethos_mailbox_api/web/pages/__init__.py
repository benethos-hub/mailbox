"""The configuration UI under ``/ui`` (CONCEPT 1): server-rendered pages.

A page calls the domain directly, as a route does, and so goes through the
same rights checks; it is not a client of the API over HTTP. The pages stay
out of the OpenAPI document. ``routes`` holds one module per area, each
with a ``router``; ``deps`` who is signed in and the CSRF check,
``session`` the sessions, ``templates`` rendering, ``errors`` the error
page.

Recipe for a page: ``routes/<area>.py`` with its routes, a template in
``templates/pages/``, the router added to ``AREAS`` below. Forms post, and answer with a
303 to a page (Post/Redirect/Get); what a view shows lives in its URL.
"""

from __future__ import annotations

from urllib.parse import quote

from fastapi import FastAPI, Request
from fastapi.responses import HTMLResponse, RedirectResponse, Response
from fastapi.staticfiles import StaticFiles
from starlette.types import ASGIApp, Message, Receive, Scope, Send

from .deps import CsrfRefused
from .errors import error_page
from .routes import accounts, home, login, users
from .session import PATH, SessionStore, SignInRequired
from .templates import STATIC_DIR, is_htmx

AREAS = (login, home, accounts, users)

# No inline script or style, no framing, nothing loaded from elsewhere.
SECURITY_HEADERS = [
    (
        b"content-security-policy",
        b"default-src 'self'; script-src 'self'; style-src 'self'; "
        b"img-src 'self' data:; frame-ancestors 'none'; form-action 'self'; "
        b"base-uri 'none'",
    ),
    (b"x-content-type-options", b"nosniff"),
    (b"referrer-policy", b"same-origin"),
    (b"cache-control", b"no-store"),
]


def _secured(app: ASGIApp) -> ASGIApp:
    """Security headers on every answer under ``/ui``."""

    async def wrapped(scope: Scope, receive: Receive, send: Send) -> None:
        if scope["type"] != "http" or not scope["path"].startswith(PATH):
            await app(scope, receive, send)
            return

        async def send_with_headers(message: Message) -> None:
            if message["type"] == "http.response.start":
                message["headers"] = [*message.get("headers", []), *SECURITY_HEADERS]
            await send(message)

        await app(scope, receive, send_with_headers)

    return wrapped


def owns(request: Request) -> bool:
    """Whether the request is one for the UI."""
    return request.url.path.startswith(PATH)


def install(app: FastAPI) -> None:
    app.state.ui_sessions = SessionStore()
    app.mount(f"{PATH}/static", StaticFiles(directory=STATIC_DIR), name="ui-static")
    for area in AREAS:
        app.include_router(area.router, prefix=PATH, include_in_schema=False)

    @app.exception_handler(SignInRequired)
    async def _sign_in(request: Request, _: SignInRequired) -> Response:
        target = f"{PATH}/login?next={quote(request.url.path)}"
        if is_htmx(request):
            return Response(status_code=204, headers={"HX-Redirect": target})
        return RedirectResponse(target, status_code=303)

    @app.exception_handler(CsrfRefused)
    async def _csrf(request: Request, _: CsrfRefused) -> HTMLResponse:
        return error_page(
            request,
            403,
            "This form is no longer valid. Reload the page and try again.",
            title="Form expired",
        )

    app.add_middleware(_Security)


class _Security:
    """``_secured`` as a Starlette middleware class."""

    def __init__(self, app: ASGIApp) -> None:
        self.app = _secured(app)

    async def __call__(self, scope: Scope, receive: Receive, send: Send) -> None:
        await self.app(scope, receive, send)
