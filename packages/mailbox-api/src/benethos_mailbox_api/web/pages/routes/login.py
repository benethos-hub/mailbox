"""Signing in with an API token, and out again."""

from __future__ import annotations

import hmac
import secrets
from typing import Annotated

from fastapi import APIRouter, Form, Request
from fastapi.responses import RedirectResponse, Response

from ....errors import MailboxApiError
from ...services import get_auth
from ..deps import Actor
from ..session import COOKIE, PATH, SignInRequired, current, store_of
from ..templates import back, local_path, render

router = APIRouter()

# Ties the sign-in form to this browser, so another site cannot sign it in
# to an account of its own (login CSRF).
LOGIN_COOKIE = "mailbox_ui_login"


@router.get("/login")
async def login_page(request: Request, next: str | None = None) -> Response:
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
    )
    response.set_cookie(
        LOGIN_COOKIE,
        nonce,
        httponly=True,
        samesite="strict",
        path=PATH,
        secure=request.url.scheme == "https",
    )
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
        return back(f"{PATH}/login", error="The sign-in form expired. Try again.")
    auth = get_auth(request)
    token = token.strip()
    try:
        auth.authenticate(token)
    except MailboxApiError:
        return back(f"{PATH}/login", error="That token is not valid.")
    session_id = store_of(request).create(token)
    response = RedirectResponse(local_path(next, PATH), status_code=303)
    response.set_cookie(
        COOKIE,
        session_id,
        httponly=True,
        samesite="strict",
        path=PATH,
        secure=request.url.scheme == "https",
    )
    response.delete_cookie(LOGIN_COOKIE, path=PATH)
    return response


@router.post("/logout")
async def logout(request: Request, _: Actor) -> Response:
    store_of(request).drop(request.cookies.get(COOKIE))
    response = back(f"{PATH}/login", message="Signed out.")
    response.delete_cookie(COOKIE, path=PATH)
    return response
