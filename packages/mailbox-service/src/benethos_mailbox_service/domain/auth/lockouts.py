"""The brakes on guessing: a client address and a user name.

Two ``SignInThrottle`` count the failures, one per client address, one
per user name whatever the address. This module asks them, tells them
of each failure and of a success, and logs when one locks out or a
lockout ends. Which credential failed stays with ``AuthService``.
"""

from __future__ import annotations

from collections.abc import Callable
from datetime import datetime, timedelta

from ...common.clock import utc_now
from ...data.models import User
from ...errors import RateLimitedError
from ..activity import ActivityLog, Actor, someone
from ..activity import auth as said
from ..rights import Access
from .throttle import SignInThrottle

# A user name that fails this often in the window waits this long, from
# any address: slower guessing at one account from many addresses, and
# never a long lockout of its owner.
NAME_LIMIT = 10
NAME_WINDOW = timedelta(minutes=15)
NAME_LOCKOUT = timedelta(minutes=1)


class Lockouts:
    def __init__(
        self,
        activity: ActivityLog,
        throttle: SignInThrottle | None = None,
        names: SignInThrottle | None = None,
        clock: Callable[[], datetime] = utc_now,
    ) -> None:
        """``throttle`` slows down a client address that fails to sign
        in, ``names`` a user name, whatever the address."""
        self._activity = activity
        self._throttle = throttle or SignInThrottle(clock=clock)
        self._names = names or SignInThrottle(
            limit=NAME_LIMIT, window=NAME_WINDOW, lockout=NAME_LOCKOUT, clock=clock
        )

    def check(self, source: str) -> None:
        """``RateLimitedError`` while the source is locked out. A lockout
        that ran out is logged here, at the next attempt."""
        if self._throttle.check(source):
            self._activity.record(said.LockoutEnded(by=someone(source)))

    def check_name(self, key: str) -> None:
        """``RateLimitedError`` while the name is braked."""
        self._names.check(key)

    def check_caller(self, access: Access, key: str) -> None:
        """``RateLimitedError`` while the caller's address or name is
        locked out."""
        if access.source is not None:
            self.check(access.source)
        self._names.check(key)

    def is_locked_out(self, source: str) -> bool:
        """Whether ``source`` failed too often to sign in, for a check that
        refuses it without telling why."""
        try:
            self.check(source)
        except RateLimitedError:
            return True
        return False

    def failed(self, source: str) -> None:
        """A failure of ``source``: a wrong credential, or one beside a
        sign-in, such as a link that does not hold."""
        if self._throttle.failed(source):
            minutes = int(self._throttle.lockout.total_seconds() // 60)
            self._activity.record(
                said.SourceLockedOut(by=someone(source), minutes=minutes)
            )

    def failed_name(self, key: str, user: User | None, by: Actor) -> None:
        """The name as typed is logged only as the user it names."""
        if self._names.failed(key):
            seconds = int(self._names.lockout.total_seconds())
            self._activity.record(said.NameBraked(by=by, user=user, seconds=seconds))

    def failed_caller(self, access: Access, key: str, user: User) -> None:
        """A wrong confirmation, counted for the address and the name."""
        if access.source is not None:
            self.failed(access.source)
        self.failed_name(key, user, Actor.of(access))

    def succeeded(self, source: str, key: str) -> None:
        """A sign-in that passed clears the source and the name."""
        self._throttle.succeeded(source)
        self._names.succeeded(key)
