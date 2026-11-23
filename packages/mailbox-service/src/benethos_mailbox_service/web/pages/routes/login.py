"""Signing in with a user name and a password, and a code of the second
factor where the user has one, out again, and changing the own
password."""

from __future__ import annotations

from typing import Annotated
from urllib.parse import urlencode

from fastapi import APIRouter, Form, Request
from fastapi.responses import HTMLResponse, RedirectResponse, Response

from benethos_mailbox_common.values import secret

from ....domain.auth import SignedIn
from ....errors import RateLimitedError, SetupRequiredError, UnauthorizedError
from ...services import Passwords, get_auth
from ...urls import client_address
from ..deps import Actor, Viewer
from ..forms import failing
from ..passkeys import answer, answered, challenge, first_way, offered, ways
from ..session import (
    COOKIE,
    PASSWORD_PAGE,
    PATH,
    SessionStore,
    SignInRequiredError,
    current,
    session_of,
    store_of,
)
from ..templates import back, local_path, render
from .factor import SIGNED_OUT

router = APIRouter()

# Ties the sign-in form to this browser, so another site cannot sign it in
# to an account of its own (login CSRF).
LOGIN_COOKIE = "mailbox_ui_login"
# A sign-in whose password was right, waiting for the code.
PENDING_COOKIE = "mailbox_ui_pending"
CODE_PAGE = f"{PATH}/login/code"

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
    "code_expired": "The time for the code ran out. Sign in again.",
    "code_tries": "Too many wrong codes. Sign in again.",
}
# What the code page says after a wrong code or passkey.
WRONG_CODE = (
    "Wrong code or passkey. Try the newest code of the app, a passkey, "
    "or a recovery code."
)
NOTICE_SIGNED_OUT = "signed_out"


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
    except SignInRequiredError:
        pass
    # Back at the sign-in, a pending one is given up.
    store_of(request).drop_pending(request.cookies.get(PENDING_COOKIE))
    nonce = secret.token(secret.SHORT)
    response = render(
        request,
        "pages/login.html",
        page="login",
        nonce=nonce,
        next=local_path(next, PATH),
        err=NOTICES.get(notice or "", "").format(minutes=max(1, minutes)) or None,
        msg="Signed out." if notice == NOTICE_SIGNED_OUT else None,
    )
    _set(response, request, LOGIN_COOKIE, nonce)
    response.delete_cookie(PENDING_COOKIE, path=PATH)
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
    if not expected or not secret.same(nonce, expected):
        return _to_login("expired")
    try:
        signed = await get_auth(request).sign_in(
            name, password, source=client_address(request)
        )
    except RateLimitedError as exc:
        return _throttled(exc)
    except SetupRequiredError:
        return _to_login("setup")
    except UnauthorizedError:
        return _to_login("invalid")
    store = store_of(request)
    # A session the browser held before is ended, never taken over.
    store.drop(request.cookies.get(COOKIE))
    store.drop_pending(request.cookies.get(PENDING_COOKIE))
    if signed.needs_code:
        pending_id = store.begin_pending(signed.user_id, local_path(next, PATH))
        response = RedirectResponse(CODE_PAGE, status_code=303)
        _set(response, request, PENDING_COOKIE, pending_id)
        response.delete_cookie(COOKIE, path=PATH)
        response.delete_cookie(LOGIN_COOKIE, path=PATH)
        return response
    return _session(request, store, signed, next)


def _session(
    request: Request, store: SessionStore, signed: SignedIn, next: str
) -> Response:
    """The session of a sign-in that passed every step. A password set by
    someone else is changed first."""
    opened = store.create(signed)
    if opened.ended:
        get_auth(request).sessions_ended(
            signed.user_id,
            source=client_address(request),
            ended=opened.ended,
            limit=store.per_user,
        )
    session_id = opened.id
    target = PASSWORD_PAGE if signed.must_change else local_path(next, PATH)
    response = RedirectResponse(target, status_code=303)
    _set(response, request, COOKIE, session_id)
    response.delete_cookie(LOGIN_COOKIE, path=PATH)
    response.delete_cookie(PENDING_COOKIE, path=PATH)
    return response


# --- the code of the second factor --------------------------------------------------


@router.get("/login/code")
async def code_page(request: Request, wrong: int = 0, code: str = "") -> Response:
    """``code``: after a wrong code of the app ("app") or a recovery code
    ("recovery"), the page shows that field first."""
    pending = store_of(request).pending(request.cookies.get(PENDING_COOKIE))
    if pending is None:
        return _to_login("code_expired")
    begun = challenge(request, pending.user_id)
    pending.challenge = begun.challenge if begun else None
    return render(
        request,
        "pages/login_code.html",
        page="login",
        nonce=pending.csrf,
        err=WRONG_CODE if wrong else None,
        ways=ways(request, pending.user_id, begun.options if begun else None),
        first=_FIRST.get(code),
    )


@router.post("/login/code")
async def sign_in_with_code(
    request: Request,
    code: Annotated[str, Form()] = "",
    nonce: Annotated[str, Form()] = "",
    passkey: Annotated[str, Form()] = "",
) -> Response:
    """The code of the app, a passkey, or a recovery code. A wrong one
    comes back to this page, the last try back to the sign-in."""
    store = store_of(request)
    pending_id = request.cookies.get(PENDING_COOKIE) or ""
    pending = store.pending(pending_id)
    if pending is None or not secret.same(nonce, pending.csrf):
        return _to_login("code_expired")
    kept, pending.challenge = pending.challenge, None
    try:
        signed = get_auth(request).sign_in_with_code(
            pending.user_id,
            code,
            source=client_address(request),
            answer=answer(request, kept, passkey),
        )
    except RateLimitedError as exc:
        store.drop_pending(pending_id)
        return _throttled(exc)
    except UnauthorizedError:
        if store.missed(pending_id):
            return RedirectResponse(_wrong(code, passkey), status_code=303)
        return _to_login("code_tries")
    store.drop_pending(pending_id)
    return _session(request, store, signed, pending.next)


def _throttled(exc: RateLimitedError) -> Response:
    """Back to the sign-in, with the whole minutes to wait, at least one."""
    return _to_login("throttled", minutes=max(1, -(-exc.retry_after // 60)))


# The method a wrong code came by, shown first again on the code page,
# by the word of its address.
_FIRST = {"app": "totp", "recovery": "recovery"}


def _wrong(code: str, passkey: str) -> str:
    """The code page after a wrong try. A code sent shows its field first
    again (``first_way``)."""
    way = first_way(code, passkey)
    if way is None:
        return f"{CODE_PAGE}?wrong=1"
    kind = next(word for word, named in _FIRST.items() if named == way)
    return f"{CODE_PAGE}?wrong=1&code={kind}"


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
    response = _to_login(NOTICE_SIGNED_OUT)
    response.delete_cookie(COOKIE, path=PATH)
    return response


# --- the own password -------------------------------------------------------------


@router.get("/password")
async def password_page(
    request: Request, caller: Viewer, passwords: Passwords
) -> HTMLResponse:
    session = current(request).session
    needs_code = passwords.needs_code(caller)
    return render(
        request,
        "pages/password.html",
        page="password",
        must_change=session.must_change,
        needs_code=needs_code,
        ways=offered(request, caller.user_id) if needs_code else None,
    )


@router.post("/password")
async def change_password(
    request: Request,
    caller: Actor,
    passwords: Passwords,
    current_password: Annotated[str, Form()] = "",
    new_password: Annotated[str, Form()] = "",
    repeat_password: Annotated[str, Form()] = "",
    code: Annotated[str, Form()] = "",
    passkey: Annotated[str, Form()] = "",
) -> Response:
    if new_password != repeat_password:
        return back(request, PASSWORD_PAGE, error="The two new passwords differ.")
    proof = answered(request, passkey)
    with failing(PASSWORD_PAGE, first=first_way(code, passkey)):
        stamp = await passwords.change_password(
            caller, current_password, new_password, code, proof
        )
    # This session carries on with the new password. Every other session
    # of the user ends at its next request. Taken from the request, since
    # checking it again with the old stamp would end it too.
    session = session_of(request)
    session.stamp = stamp
    session.must_change = False
    return back(request, PATH, f"Password changed. {SIGNED_OUT}")
