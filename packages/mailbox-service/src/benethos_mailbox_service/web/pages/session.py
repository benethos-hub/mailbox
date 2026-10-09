"""Sessions of the configuration UI (CONCEPT 1, 7.5).

A person signs in with a user name and a password. The session lives on
the server: the cookie carries only a random id, the session the id of its
user and when that user's password and second factor were set. Every
request loads the user anew, so a disabled user, changed rights, a changed
password or factor take effect at once. A restart signs everyone out.
A session ends after some hours without a request, and after a day
whatever it did. A user holds a few at most: a new one ends the oldest.

A user with a second factor gets no session for the password alone, but a
pending sign-in with a cookie of its own. It reaches the code page and
nothing else, and ends after a few minutes or a few wrong codes
(docs/AUTHENTICATION.md 3).

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
from ...domain.auth import CODE_TRIES, PENDING, SignedIn
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
# How long a session lives at most, used or not.
MAX_AGE = timedelta(hours=24)
# Sessions of one user at most. A new one ends the oldest.
PER_USER = 10
# How long something shown once waits for the page that shows it.
SHOWN_ONCE = timedelta(minutes=5)
# Where a password set by someone else is changed. Until then the session
# reaches this page and signing out, nothing else.
PASSWORD_PAGE = f"{PATH}/password"
_WHILE_CHANGING = {PASSWORD_PAGE, f"{PATH}/logout"}


@dataclass(frozen=True)
class PendingTotp:
    """A secret shown for a new TOTP device, not confirmed yet. Never
    stored before its first code."""

    name: str
    secret: bytes
    until: datetime


@dataclass(frozen=True)
class Kept:
    """Something shown on the next page only, until a time."""

    value: str
    until: datetime


@dataclass
class UiSession:
    user_id: str
    # When the user's password was set: the session ends once it changes.
    stamp: datetime
    must_change: bool
    csrf: str
    last_seen: datetime
    created: datetime
    # The sign-in before this session's, shown on the overview.
    previous_sign_in: datetime | None = None
    # Which devices of a second factor the user had at the sign-in, None
    # without one: the session ends once a device is added or removed.
    factor: str | None = None
    # A TOTP device being added in this session.
    totp: PendingTotp | None = None
    # Shown on the next page only, e.g. a new token: kept here, never in a
    # URL, and gone once shown or once its time ran out.
    once: dict[str, Kept] = field(default_factory=dict)


@dataclass
class PendingSignIn:
    """The password was right, the code of the second factor is next."""

    user_id: str
    # Where to go once signed in.
    next: str
    csrf: str
    until: datetime
    tries_left: int = CODE_TRIES


class SignInRequiredError(Exception):
    """No valid session: the page answers with the sign-in page."""


class PasswordChangeRequiredError(Exception):
    """The password was set by someone else: it is changed first."""


class SessionStore:
    def __init__(
        self,
        clock: Callable[[], datetime] = utc_now,
        idle: timedelta = IDLE,
        max_age: timedelta = MAX_AGE,
        per_user: int = PER_USER,
        shown_once: timedelta = SHOWN_ONCE,
    ) -> None:
        self._sessions: dict[str, UiSession] = {}
        self._pending: dict[str, PendingSignIn] = {}
        self._clock = clock
        self._idle = idle
        self._max_age = max_age
        self._per_user = per_user
        self._shown_once = shown_once

    @property
    def idle(self) -> timedelta:
        """How long a session lives without a request."""
        return self._idle

    @property
    def max_age(self) -> timedelta:
        """How long a session lives at most, used or not."""
        return self._max_age

    def create(self, signed: SignedIn) -> str:
        """A new session, with an id of its own: one the browser held
        before signing in is never taken over. The user's oldest sessions
        end, so it holds no more than its limit."""
        now = self._clock()
        # Sessions nobody came back to would stay for the life of the
        # process. Each sign-in sweeps them.
        for stale in [s for s, v in self._sessions.items() if not self._alive(v, now)]:
            del self._sessions[stale]
        own = sorted(
            (v.created, s)
            for s, v in self._sessions.items()
            if v.user_id == signed.user_id
        )
        for _, oldest in own[: max(0, len(own) - self._per_user + 1)]:
            del self._sessions[oldest]
        session_id = token()
        self._sessions[session_id] = UiSession(
            user_id=signed.user_id,
            stamp=signed.stamp,
            must_change=signed.must_change,
            csrf=token(),
            last_seen=now,
            created=now,
            previous_sign_in=signed.previous,
            factor=signed.factor,
        )
        return session_id

    def _alive(self, session: UiSession, now: datetime) -> bool:
        """Not idle too long, and not older than the longest a session
        lives."""
        return (
            now - session.last_seen <= self._idle
            and now - session.created <= self._max_age
        )

    def keep_once(self, session: UiSession, key: str, value: str) -> None:
        """``value`` for the next page that asks for ``key``, for a few
        minutes at most."""
        session.once[key] = Kept(value, self._clock() + self._shown_once)

    def take_once(self, session: UiSession, key: str) -> str | None:
        """What ``keep_once`` kept under ``key``, once, unless its time
        ran out. Whatever ran out goes too."""
        now = self._clock()
        for gone in [k for k, kept in session.once.items() if kept.until <= now]:
            del session.once[gone]
        kept = session.once.pop(key, None)
        return kept.value if kept is not None else None

    def begin_pending(self, user_id: str, next: str) -> str:
        """A pending sign-in, with an id of its own for its cookie."""
        now = self._clock()
        for gone in [p for p, v in self._pending.items() if v.until <= now]:
            del self._pending[gone]
        pending_id = token()
        self._pending[pending_id] = PendingSignIn(
            user_id, next, csrf=token(), until=now + PENDING
        )
        return pending_id

    def pending(self, pending_id: str | None) -> PendingSignIn | None:
        """The pending sign-in, unless it is unknown or ran out."""
        found = self._pending.get(pending_id) if pending_id else None
        if found is None or found.until <= self._clock():
            self.drop_pending(pending_id)
            return None
        return found

    def missed(self, pending_id: str) -> bool:
        """One wrong code. False once no try is left: then it is gone."""
        found = self._pending.get(pending_id)
        if found is None:
            return False
        found.tries_left -= 1
        if found.tries_left <= 0:
            self.drop_pending(pending_id)
            return False
        return True

    def drop_pending(self, pending_id: str | None) -> None:
        if pending_id:
            self._pending.pop(pending_id, None)

    def known(self, session_id: str | None) -> bool:
        """Whether the session exists and is not idle too long. Unlike
        ``get``, the look does not count as the session being used."""
        session = self._sessions.get(session_id) if session_id else None
        return session is not None and self._alive(session, self._clock())

    def get(self, session_id: str | None) -> UiSession | None:
        """The session, unless it is unknown, was idle too long or is
        older than the longest a session lives."""
        if not session_id:
            return None
        session = self._sessions.get(session_id)
        now = self._clock()
        if session is None or not self._alive(session, now):
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
            session.user_id,
            session.stamp,
            factor=session.factor,
            source=client_address(request),
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
    store_of(request).keep_once(session_of(request), key, value)


def take_once(request: Request, key: str) -> str | None:
    """What ``show_once`` kept under ``key``, once."""
    return store_of(request).take_once(session_of(request), key)


def session_of(request: Request) -> UiSession:
    """The session ``current`` found for this request, else looked up."""
    return (found_for(request) or current(request)).session


def csrf_ok(session: UiSession, presented: str | None) -> bool:
    return presented is not None and same(presented, session.csrf)
