"""Sessions of the configuration UI (CONCEPT 1, 7.5).

A person signs in with an API token of its user, or the admin key. The
session lives on the server: the cookie carries only a random id, the token
stays in memory here and never reaches the browser again. Every request
authenticates the token anew, so a revoked token, a disabled user or
changed rights take effect at once, as on the API. A restart signs
everyone out.

Forms carry a CSRF token of the session, checked on every request that
changes something. The cookie is ``HttpOnly`` and ``SameSite=Strict`` too.
"""

from __future__ import annotations

import hmac
import secrets
from collections.abc import Callable
from dataclasses import dataclass, field
from datetime import datetime, timedelta

from fastapi import Request

from ...common.clock import utc_now
from ...domain.access import Access
from ...errors import MailboxApiError
from ..services import get_auth

COOKIE = "mailbox_ui_session"
PATH = "/ui"
CSRF_FIELD = "csrf_token"
CSRF_HEADER = "X-CSRF-Token"
IDLE = timedelta(hours=8)


@dataclass
class UiSession:
    token: str
    csrf: str
    last_seen: datetime
    # Shown on the next page only, e.g. a new token: kept here, never in a
    # URL, and gone once shown.
    once: dict[str, str] = field(default_factory=dict)


class SignInRequired(Exception):
    """No valid session: the page answers with the sign-in page."""


class SessionStore:
    def __init__(self, clock: Callable[[], datetime] = utc_now) -> None:
        self._sessions: dict[str, UiSession] = {}
        self._clock = clock

    def create(self, token: str) -> str:
        session_id = secrets.token_urlsafe(32)
        self._sessions[session_id] = UiSession(
            token=token, csrf=secrets.token_urlsafe(32), last_seen=self._clock()
        )
        return session_id

    def get(self, session_id: str | None) -> UiSession | None:
        """The session, unless it is unknown or was idle too long."""
        if not session_id:
            return None
        session = self._sessions.get(session_id)
        now = self._clock()
        if session is None or now - session.last_seen > IDLE:
            self._sessions.pop(session_id, None)
            return None
        session.last_seen = now
        return session

    def drop(self, session_id: str | None) -> None:
        if session_id:
            self._sessions.pop(session_id, None)


def store_of(request: Request) -> SessionStore:
    store: SessionStore = request.app.state.ui_sessions
    return store


def current(request: Request) -> tuple[UiSession, Access]:
    """The session and who it belongs to, or ``SignInRequired``."""
    session = store_of(request).get(request.cookies.get(COOKIE))
    if session is None:
        raise SignInRequired
    auth = get_auth(request)
    try:
        access = auth.authenticate(session.token)
    except MailboxApiError:
        # Revoked, expired or disabled since the sign-in.
        store_of(request).drop(request.cookies.get(COOKIE))
        raise SignInRequired from None
    request.state.ui_session = session
    request.state.access = access
    return session, access


def show_once(request: Request, key: str, value: str) -> None:
    """Keep ``value`` for the next page that asks for ``key``."""
    current(request)[0].once[key] = value


def take_once(request: Request, key: str) -> str | None:
    """What ``show_once`` kept under ``key``, once."""
    return current(request)[0].once.pop(key, None)


def csrf_ok(session: UiSession, presented: str | None) -> bool:
    return presented is not None and hmac.compare_digest(
        presented.encode(), session.csrf.encode()
    )
