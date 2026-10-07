"""Sessions of the configuration UI (CONCEPT 1, 7.5).

A person signs in with a user name and a password. The session lives on
the server: the cookie carries only a random id, the session the id of its
user and when that user's password was set. Every request loads the user
anew, so a disabled user, changed rights or a changed password take
effect at once. A restart signs everyone out.

Forms carry a CSRF token of the session, checked on every request that
changes something. The cookie is ``HttpOnly`` and ``SameSite=Strict`` too.
"""

from __future__ import annotations

from collections.abc import Callable
from dataclasses import dataclass, field
from datetime import datetime, timedelta

from fastapi import Request

from ...common.clock import utc_now
from ...common.secret import same, token
from ...domain.auth import SignedIn
from ...domain.rights import Access
from ...errors import MailboxServiceError
from ..limits import signed_in
from ..services import get_auth
from ..state import app_sessions
from ..urls import client_address

COOKIE = "mailbox_ui_session"
PATH = "/ui"
CSRF_FIELD = "csrf_token"
CSRF_HEADER = "X-CSRF-Token"
IDLE = timedelta(hours=8)
# Where a password set by someone else is changed. Until then the session
# reaches this page and signing out, nothing else.
PASSWORD_PAGE = f"{PATH}/password"
_WHILE_CHANGING = {PASSWORD_PAGE, f"{PATH}/logout"}


@dataclass
class UiSession:
    user_id: str
    # When the user's password was set: the session ends once it changes.
    stamp: datetime
    must_change: bool
    csrf: str
    last_seen: datetime
    # The sign-in before this session's, shown on the overview.
    previous_sign_in: datetime | None = None
    # Shown on the next page only, e.g. a new token: kept here, never in a
    # URL, and gone once shown.
    once: dict[str, str] = field(default_factory=dict)


class SignInRequiredError(Exception):
    """No valid session: the page answers with the sign-in page."""


class PasswordChangeRequiredError(Exception):
    """The password was set by someone else: it is changed first."""


class SessionStore:
    def __init__(
        self, clock: Callable[[], datetime] = utc_now, idle: timedelta = IDLE
    ) -> None:
        self._sessions: dict[str, UiSession] = {}
        self._clock = clock
        self._idle = idle

    @property
    def idle(self) -> timedelta:
        """How long a session lives without a request."""
        return self._idle

    def create(self, signed: SignedIn) -> str:
        """A new session, with an id of its own: one the browser held
        before signing in is never taken over."""
        now = self._clock()
        # Sessions nobody came back to would stay for the life of the
        # process. Each sign-in sweeps them.
        idle = self._idle
        for stale in [s for s, v in self._sessions.items() if now - v.last_seen > idle]:
            del self._sessions[stale]
        session_id = token()
        self._sessions[session_id] = UiSession(
            user_id=signed.user_id,
            stamp=signed.stamp,
            must_change=signed.must_change,
            csrf=token(),
            last_seen=now,
            previous_sign_in=signed.previous,
        )
        return session_id

    def known(self, session_id: str | None) -> bool:
        """Whether the session exists and is not idle too long. Unlike
        ``get``, the look does not count as the session being used."""
        session = self._sessions.get(session_id) if session_id else None
        return session is not None and self._clock() - session.last_seen <= self._idle

    def get(self, session_id: str | None) -> UiSession | None:
        """The session, unless it is unknown or was idle too long."""
        if not session_id:
            return None
        session = self._sessions.get(session_id)
        now = self._clock()
        if session is None or now - session.last_seen > self._idle:
            self._sessions.pop(session_id, None)
            return None
        session.last_seen = now
        return session

    def drop(self, session_id: str | None) -> None:
        if session_id:
            self._sessions.pop(session_id, None)

    def __len__(self) -> int:
        """How many sessions it holds, idle ones not yet swept among them."""
        return len(self._sessions)


def store_of(request: Request) -> SessionStore:
    return app_sessions(request.app)


def carries_session(request: Request) -> bool:
    """Whether the request comes with a session of the UI that is known."""
    return store_of(request).known(request.cookies.get(COOKIE))


@dataclass(frozen=True)
class Current:
    """A page request's session and who it belongs to."""

    session: UiSession
    access: Access


# Where ``current`` keeps what it found, for the rest of the request.
_FOUND = "ui_current"


def current(request: Request) -> Current:
    """The session and who it belongs to, or ``SignInRequiredError``. While its
    password must be changed, ``PasswordChangeRequiredError`` on any other page.
    The first call of a request counts it against the session's limit."""
    session_id = request.cookies.get(COOKIE)
    session = store_of(request).get(session_id)
    if session_id is None or session is None:
        raise SignInRequiredError
    auth = get_auth(request)
    try:
        access = auth.session_access(
            session.user_id, session.stamp, source=client_address(request)
        )
    except MailboxServiceError:
        # Gone, disabled, or its password changed since the sign-in.
        store_of(request).drop(request.cookies.get(COOKIE))
        raise SignInRequiredError from None
    if found_for(request) is None:
        signed_in(request, f"session:{session_id}", access)
    found = Current(session, access)
    setattr(request.state, _FOUND, found)
    if session.must_change and request.url.path not in _WHILE_CHANGING:
        raise PasswordChangeRequiredError
    return found


def found_for(request: Request) -> Current | None:
    """What ``current`` found for this request. None before it ran, or
    when the request has no session."""
    found = getattr(request.state, _FOUND, None)
    return found if isinstance(found, Current) else None


def show_once(request: Request, key: str, value: str) -> None:
    """Keep ``value`` for the next page that asks for ``key``."""
    session_of(request).once[key] = value


def take_once(request: Request, key: str) -> str | None:
    """What ``show_once`` kept under ``key``, once."""
    return session_of(request).once.pop(key, None)


def session_of(request: Request) -> UiSession:
    """The session ``current`` found for this request, else looked up."""
    return (found_for(request) or current(request)).session


def csrf_ok(session: UiSession, presented: str | None) -> bool:
    return presented is not None and same(presented, session.csrf)
