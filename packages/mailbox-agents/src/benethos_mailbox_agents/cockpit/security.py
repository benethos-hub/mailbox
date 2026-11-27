"""What guards the cockpit: the sessions of the people signed in, the
count of failed sign-ins per address, and the headers of every answer.

Both live in the memory of the process: a restart signs everyone out and
forgets every failure. The numbers are those of the mailbox service.
"""

from __future__ import annotations

from collections import deque
from dataclasses import dataclass, field
from datetime import datetime, timedelta

from benethos_mailbox_common.values import secret

__all__ = [
    "COOKIE",
    "LOGIN_COOKIE",
    "Session",
    "Sessions",
    "Throttle",
    "headers",
]

COOKIE = "mailbox_cockpit_session"
# The nonce of the sign-in form, so a page of elsewhere cannot sign a
# browser in with a secret of its own.
LOGIN_COOKIE = "mailbox_cockpit_login"

IDLE = timedelta(hours=8)
MAX_AGE = timedelta(hours=24)

# Failed sign-ins from one address within WINDOW before it waits LOCKOUT.
LIMIT = 10
WINDOW = timedelta(minutes=15)
LOCKOUT = timedelta(minutes=15)
# The addresses kept at most, the oldest dropped first.
MAX_SOURCES = 10_000

_POLICY = (
    "default-src 'self'; script-src 'none'; style-src 'self'; "
    "img-src 'self' data:; frame-ancestors 'none'; form-action 'self'; "
    "base-uri 'none'"
)


def headers(static: bool) -> dict[str, str]:
    """The headers of every answer: a page is never kept, a static file is
    kept and asked for again before use."""
    return {
        "content-security-policy": _POLICY,
        "x-content-type-options": "nosniff",
        "referrer-policy": "same-origin",
        "cache-control": "no-cache" if static else "no-store",
    }


@dataclass
class Session:
    """One person signed in. ``token`` guards the form that signs out."""

    id: str
    token: str
    started: datetime
    seen: datetime


@dataclass
class Sessions:
    """The sessions of the process, by id."""

    _found: dict[str, Session] = field(default_factory=dict)

    def start(self, now: datetime) -> Session:
        self._sweep(now)
        session = Session(secret.token(), secret.token(), now, now)
        self._found[session.id] = session
        return session

    def get(self, session_id: str | None, now: datetime) -> Session | None:
        """The session of ``session_id`` while it lives, seen at ``now``."""
        found = self._found.get(session_id or "")
        if found is None:
            return None
        if not _alive(found, now):
            self._found.pop(found.id, None)
            return None
        found.seen = now
        return found

    def end(self, session_id: str) -> None:
        self._found.pop(session_id, None)

    def _sweep(self, now: datetime) -> None:
        for gone in [s.id for s in self._found.values() if not _alive(s, now)]:
            del self._found[gone]


def _alive(session: Session, now: datetime) -> bool:
    return now - session.seen <= IDLE and now - session.started <= MAX_AGE


@dataclass
class Throttle:
    """Failed sign-ins per address of the caller."""

    _failures: dict[str, deque[datetime]] = field(default_factory=dict)
    _locked: dict[str, datetime] = field(default_factory=dict)

    def wait(self, source: str, now: datetime) -> int:
        """The seconds ``source`` must wait before it may try again, 0
        when it may now."""
        until = self._locked.get(source)
        if until is None or until <= now:
            self._locked.pop(source, None)
            return 0
        return max(1, int((until - now).total_seconds()))

    def failed(self, source: str, now: datetime) -> None:
        found = self._failures.pop(source, deque())
        found.append(now)
        while found and now - found[0] > WINDOW:
            found.popleft()
        if len(found) >= LIMIT:
            self._locked[source] = now + LOCKOUT
            found.clear()
        self._failures[source] = found
        for kept in (self._failures, self._locked):
            while len(kept) > MAX_SOURCES:
                del kept[next(iter(kept))]

    def succeeded(self, source: str) -> None:
        self._failures.pop(source, None)
