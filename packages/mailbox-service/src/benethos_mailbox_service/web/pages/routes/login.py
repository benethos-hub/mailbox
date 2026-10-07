"""Signing in with a user name and a password, out again, and changing
the own password."""

from __future__ import annotations

import hmac
import secrets
from typing import Annotated
from urllib.parse import urlencode

from fastapi import APIRouter, Form, Request
from fastapi.responses import HTMLResponse, RedirectResponse, Response

from ....errors import RateLimitedError, SetupRequiredError, UnauthorizedError
from ...services import Passwords, get_auth
from ...urls import client_address
from ..deps import Actor, Viewer
from ..forms import failing
from ..session import (
    COOKIE,
    PASSWORD_PAGE,
    PATH,
    SignInRequired,
    UiSession,
    current,
    store_of,
)
from ..templates import back, local_path, render

router = APIRouter()

# Ties the sign-in form to this browser, so another site cannot sign it in
# to an account of its own (login CSRF).
LOGIN_COOKIE = "mailbox_ui_login"

# What the sign-in page says after a redirect. Without a session there is
# nowhere to keep a message, so the URL names one of these, never a text.
NOTICES = {
    "expired": "The sign-in form expired. Try again.",
    "invalid": "Wrong user name or password.",
    "throttled": "Too many failed attempts. Try again in {minutes} minutes.",
    "setup": (
        "No user exists yet. Run `benethos-mailbox-service users create-admin` "
        "on the host."
    ),
}
SIGNED_OUT = "signed_out"


@router.get("/login")
async def login_page(
    request: Request,
    next: str | None = None,
    notice: str | None = None,
    minutes: int = 1,
) -> Response:
    try:
        current(request)
        return RedirectResponse(local_path(next, PATH), status_code=303)
    except SignInRequired:
        pass
    nonce = secrets.token_urlsafe(24)
    response = render(
        request,
        "pages/login.html",
        page="login",
        nonce=nonce,
        next=local_path(next, PATH),
        err=NOTICES.get(notice or "", "").format(minutes=max(1, minutes)) or None,
        msg="Signed out." if notice == SIGNED_OUT else None,
    )
    _set(response, request, LOGIN_COOKIE, nonce)
    return response


@router.post("/login")
async def login(
    request: Request,
    name: Annotated[str, Form()] = "",
    password: Annotated[str, Form()] = "",
    nonce: Annotated[str, Form()] = "",
    next: Annotated[str, Form()] = PATH,
) -> Response:
    expected = request.cookies.get(LOGIN_COOKIE) or ""
    if not expected or not hmac.compare_digest(nonce.encode(), expected.encode()):
        return _to_login("expired")
    try:
        signed = await get_auth(request).sign_in(
            name, password, source=client_address(request)
        )
    except RateLimitedError as exc:
        minutes = max(1, -(-exc.retry_after // 60))
        return _to_login("throttled", minutes=minutes)
    except SetupRequiredError:
        return _to_login("setup")
    except UnauthorizedError:
        return _to_login("invalid")
    store = store_of(request)
    # A session the browser held before is ended, never taken over.
    store.drop(request.cookies.get(COOKIE))
    session_id = store.create(signed)
    target = PASSWORD_PAGE if signed.must_change else local_path(next, PATH)
    response = RedirectResponse(target, status_code=303)
    _set(response, request, COOKIE, session_id)
    response.delete_cookie(LOGIN_COOKIE, path=PATH)
    return response


def _to_login(notice: str, **values: int) -> Response:
    query = urlencode({"notice": notice, **values})
    return RedirectResponse(f"{PATH}/login?{query}", status_code=303)


def _set(response: Response, request: Request, name: str, value: str) -> None:
    """A cookie of the UI: scripts cannot read it, other sites cannot send
    it, and over HTTPS it stays there."""
    response.set_cookie(
        name,
        value,
        httponly=True,
        samesite="strict",
        path=PATH,
        secure=request.url.scheme == "https",
    )


@router.post("/logout")
async def logout(request: Request, caller: Actor) -> Response:
    store_of(request).drop(request.cookies.get(COOKIE))
    get_auth(request).sign_out(caller)
    response = _to_login(SIGNED_OUT)
    response.delete_cookie(COOKIE, path=PATH)
    return response


# --- the own password -------------------------------------------------------------


@router.get("/password")
async def password_page(request: Request, _: Viewer) -> HTMLResponse:
    session, _access = current(request)
    return render(
        request, "pages/password.html", page="password", must_change=session.must_change
    )


@router.post("/password")
async def change_password(
    request: Request,
    caller: Actor,
    passwords: Passwords,
    current_password: Annotated[str, Form()] = "",
    new_password: Annotated[str, Form()] = "",
    repeat_password: Annotated[str, Form()] = "",
) -> Response:
    if new_password != repeat_password:
        return back(request, PASSWORD_PAGE, error="The two new passwords differ.")
    with failing(PASSWORD_PAGE):
        stamp = await passwords.change_password(caller, current_password, new_password)
    # This session carries on with the new password. Every other session
    # of the user ends at its next request. Taken from the request, since
    # checking it again with the old stamp would end it too.
    session: UiSession = request.state.ui_session
    session.stamp = stamp
    session.must_change = False
    return back(request, PATH, "Password changed. Other sessions are signed out.")
