"""The configuration UI under ``/ui`` (CONCEPT 1): server-rendered pages.

A page calls the domain directly, as a route does, and so goes through the
same rights checks. It is not a client of the API over HTTP. The pages stay
out of the OpenAPI document. ``routes`` holds one module per area, each
with a ``router``. ``deps`` holds who is signed in and the CSRF check,
``session`` the sessions, ``templates`` rendering, ``errors`` the error
page.

Recipe for a page: ``routes/<area>.py`` with its routes, a template in
``templates/pages/``, the router added to ``AREAS`` below. Forms post,
and answer with a 303 to a page (Post/Redirect/Get). What a view shows
lives in its URL.
"""

from __future__ import annotations

from datetime import timedelta

from fastapi import FastAPI, Request
from fastapi.staticfiles import StaticFiles

from ..state import app_services, app_settings
from . import handlers
from .deps import CsrfRefusedError
from .forms import FormFailedError
from .routes import (
    accounts,
    audit,
    compose,
    drafts,
    factor,
    folders,
    home,
    login,
    mail,
    messages,
    oauth,
    roles,
    sends,
    system,
    tokens,
    totp,
    users,
    webhooks,
)
from .security import Security, security_headers
from .session import (
    PATH,
    PasswordChangeRequiredError,
    SessionStore,
    SignInRequiredError,
)
from .templates import STATIC_DIR

AREAS = (
    login,
    home,
    accounts,
    mail,
    messages,
    folders,
    compose,
    drafts,
    sends,
    oauth,
    system,
    audit,
    users,
    tokens,
    factor,
    totp,
    roles,
    webhooks,
)


STATIC = f"{PATH}/static"


def owns(request: Request) -> bool:
    """Whether the request is one for the UI."""
    return request.url.path.startswith(PATH)


def install(app: FastAPI) -> None:
    settings = app_settings(app)
    app.state.ui_sessions = SessionStore(
        idle=timedelta(hours=settings.session_idle_hours),
        max_age=timedelta(hours=settings.session_max_hours),
        per_user=settings.sessions_per_user,
        shown_once=timedelta(minutes=settings.shown_once_minutes),
    )
    app.mount(STATIC, StaticFiles(directory=STATIC_DIR), name="ui-static")
    for area in AREAS:
        app.include_router(area.router, prefix=PATH, include_in_schema=False)

    app.exception_handler(SignInRequiredError)(handlers.sign_in_required)
    app.exception_handler(PasswordChangeRequiredError)(
        handlers.password_change_required
    )
    app.exception_handler(FormFailedError)(handlers.form_failed)
    app.exception_handler(CsrfRefusedError)(handlers.csrf_refused)
    hosts = app_services(app).oauth.sign_in_hosts()
    app.add_middleware(Security, headers=security_headers(hosts), static=STATIC)
