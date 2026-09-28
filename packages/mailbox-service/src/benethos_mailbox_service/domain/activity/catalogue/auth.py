"""Sign-in and sessions (docs/LOGGING.md 5.2)."""

from __future__ import annotations

import logging
from dataclasses import dataclass
from typing import ClassVar

from ....data.models import User
from ..base import Activity, user


@dataclass(frozen=True, kw_only=True)
class UiSignIn(Activity):
    def says(self) -> str:
        return "signed in to the UI"


@dataclass(frozen=True, kw_only=True)
class UiSignInFailed(Activity):
    """``user`` only when the name typed is a user's: a password typed
    into the name field must not reach the log."""

    level: ClassVar[int] = logging.WARNING

    user: User | None
    reason: str

    def says(self) -> str:
        who = user(self.user) if self.user is not None else "an unknown name"
        return f"failed to sign in to the UI as {who}"

    def why(self) -> str:
        return self.reason


@dataclass(frozen=True, kw_only=True)
class ConfirmFailed(Activity):
    level: ClassVar[int] = logging.WARNING

    def says(self) -> str:
        return "typed a wrong password to confirm a step"


@dataclass(frozen=True, kw_only=True)
class SignedOut(Activity):
    def says(self) -> str:
        return "signed out of the UI"


@dataclass(frozen=True, kw_only=True)
class TokenRefused(Activity):
    """A token the service knows, but no longer takes. One it does not
    know at all counts against the sign-in throttle alone."""

    level: ClassVar[int] = logging.WARNING

    token_id: str
    token_name: str
    user_id: str
    reason: str

    def says(self) -> str:
        return f"presented token {self.token_name} ({self.token_id}) of {self.user_id}"

    def why(self) -> str:
        return self.reason
