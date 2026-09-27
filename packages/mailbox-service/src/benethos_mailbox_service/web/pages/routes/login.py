"""Signing in with an API token, and out again."""

from __future__ import annotations

import hmac
import secrets
from typing import Annotated
from urllib.parse import urlencode

from fastapi import APIRouter, Form, Request
from fastapi.responses import RedirectResponse, Response

from ....errors import MailboxServiceError, RateLimitedError
from ...services import get_auth
from ...urls import client_address
from ..deps import Actor
from ..session import COOKIE, PATH, SignInRequired, current, store_of
from ..templates import local_path, render

router = APIRouter()

# Ties the sign-in form to this browser, so another site cannot sign it in
# to an account of its own (login CSRF).
LOGIN_COOKIE = "mailbox_ui_login"

# What the sign-in page says after a redirect. Without a session there is
# nowhere to keep a message, so the URL names one of these, never a text.
NOTICES = {
    "expired": "The sign-in form expired. Try again.",
    "invalid": "That token is not valid.",
    "throttled": "Too many failed attempts. Try again in {minutes} minutes.",
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
    token: Annotated[str, Form()],
    nonce: Annotated[str, Form()] = "",
    next: Annotated[str, Form()] = PATH,
) -> Response:
    expected = request.cookies.get(LOGIN_COOKIE) or ""
    if not expected or not hmac.compare_digest(nonce.encode(), expected.encode()):
        return _to_login("expired")
    auth = get_auth(request)
    token = token.strip()
    try:
        auth.authenticate(token, source=client_address(request))
    except RateLimitedError as exc:
        minutes = max(1, -(-exc.retry_after // 60))
        return _to_login("throttled", minutes=minutes)
    except MailboxServiceError:
        return _to_login("invalid")
    session_id = store_of(request).create(token)
    response = RedirectResponse(local_path(next, PATH), status_code=303)
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
async def logout(request: Request, _: Actor) -> Response:
    store_of(request).drop(request.cookies.get(COOKIE))
    response = _to_login(SIGNED_OUT)
    response.delete_cookie(COOKIE, path=PATH)
    return response
