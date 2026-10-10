"""What a sign-in to the UI answers: who signed in (``SignedIn``), and
how a user signs in (``SignInState``). Values only, the decisions are
``AuthService``'s.
"""

from __future__ import annotations

from dataclasses import dataclass
from datetime import datetime


@dataclass(frozen=True, slots=True)
class SignInState:
    """How a user signs in to the UI, never the password itself."""

    has_password: bool
    # Set by someone else, or a one-time password: changed at the next
    # sign-in. False without a password.
    must_change: bool
    last_sign_in_at: datetime | None
    # A code of an authenticator app is asked after the password.
    second_factor: bool = False


@dataclass(frozen=True, slots=True)
class SignedIn:
    """Who signed in with a password, for a session of the UI."""

    user_id: str
    # The password was set by someone else: it must be changed first.
    must_change: bool
    # When the password was set. The session keeps it and ends once the
    # password changes.
    stamp: datetime
    # The sign-in before this one, to show the user.
    previous: datetime | None = None
    # The password was right, the code of the second factor comes next:
    # no session yet, a pending sign-in.
    needs_code: bool = False
    # Which devices of a second factor the user has, None without one. The
    # session keeps it and ends once a device is added or removed.
    factor: str | None = None
