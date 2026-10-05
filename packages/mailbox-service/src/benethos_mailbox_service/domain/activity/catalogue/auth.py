"""Sign-in and sessions, and the brakes on failed sign-ins
(docs/LOGGING.md 5.2, 5.9)."""

from __future__ import annotations

import logging
from dataclasses import dataclass
from typing import ClassVar

from ....data.models import ActivityOutcome, User
from ..base import Activity, user


@dataclass(frozen=True, kw_only=True)
class UiSignIn(Activity):
    name: ClassVar[str] = "signed_in"
    audited: ClassVar[bool] = True

    def says(self) -> str:
        return "signed in to the UI"


@dataclass(frozen=True, kw_only=True)
class UiSignInFailed(Activity):
    """``user`` only when the name typed is a user's: a password typed
    into the name field must not reach the log."""

    name: ClassVar[str] = "sign_in_failed"
    audited: ClassVar[bool] = True
    outcome: ClassVar[ActivityOutcome] = "refused"
    level: ClassVar[int] = logging.WARNING

    user: User | None
    reason: str

    def says(self) -> str:
        who = user(self.user) if self.user is not None else "an unknown name"
        return f"failed to sign in to the UI as {who}"

    def why(self) -> str:
        return self.reason

    def touched(self) -> str | None:
        return self.user.id if self.user else None


@dataclass(frozen=True, kw_only=True)
class SignedOut(Activity):
    name: ClassVar[str] = "signed_out"

    def says(self) -> str:
        return "signed out of the UI"


@dataclass(frozen=True, kw_only=True)
class ConfirmFailed(Activity):
    name: ClassVar[str] = "confirm_failed"
    audited: ClassVar[bool] = True
    outcome: ClassVar[ActivityOutcome] = "refused"
    level: ClassVar[int] = logging.WARNING

    def says(self) -> str:
        return "typed a wrong password to confirm a step"


@dataclass(frozen=True, kw_only=True)
class TokenRefused(Activity):
    """A token the service knows, but no longer takes. One it does not
    know at all counts against the sign-in throttle alone."""

    name: ClassVar[str] = "token_refused"
    audited: ClassVar[bool] = True
    outcome: ClassVar[ActivityOutcome] = "refused"
    level: ClassVar[int] = logging.WARNING

    token_id: str
    token_name: str
    user_id: str
    reason: str

    def says(self) -> str:
        return f"presented token {self.token_name} ({self.token_id}) of {self.user_id}"

    def why(self) -> str:
        return self.reason

    def touched(self) -> str | None:
        return self.token_id


@dataclass(frozen=True, kw_only=True)
class SourceLockedOut(Activity):
    """Too many failed sign-ins from one client address. ``by`` is that
    address."""

    name: ClassVar[str] = "locked_out"
    audited: ClassVar[bool] = True
    outcome: ClassVar[ActivityOutcome] = "refused"
    level: ClassVar[int] = logging.WARNING

    minutes: int

    def says(self) -> str:
        return "failed to sign in too often"

    def why(self) -> str:
        return f"locked out for {self.minutes} minutes"


@dataclass(frozen=True, kw_only=True)
class LockoutEnded(Activity):
    """Noticed at the next attempt after the lockout ran out."""

    name: ClassVar[str] = "lockout_ended"

    def says(self) -> str:
        return "may try to sign in again"

    def why(self) -> str:
        return "the lockout ended"


@dataclass(frozen=True, kw_only=True)
class NameBraked(Activity):
    """Too many failed sign-ins as one user name, from any address. The
    user when the name is a user's, else nobody: the name as typed may be
    a password."""

    name: ClassVar[str] = "name_braked"
    audited: ClassVar[bool] = True
    outcome: ClassVar[ActivityOutcome] = "refused"
    level: ClassVar[int] = logging.WARNING

    user: User | None
    seconds: int

    def says(self) -> str:
        who = user(self.user) if self.user is not None else "an unknown name"
        return f"failed to sign in as {who} too often"

    def why(self) -> str:
        return f"the name waits {self.seconds} seconds"

    def touched(self) -> str | None:
        return self.user.id if self.user else None
