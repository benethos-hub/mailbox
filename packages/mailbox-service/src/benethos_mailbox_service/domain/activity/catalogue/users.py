"""Users, passwords, tokens, roles (docs/LOGGING.md 5.3)."""

from __future__ import annotations

from dataclasses import dataclass

from ....data.models import User
from ..base import Activity, plural, user


@dataclass(frozen=True, kw_only=True)
class UserDeleted(Activity):
    user: User
    webhooks: int

    def says(self) -> str:
        return (
            f"deleted user {user(self.user)} and its {plural(self.webhooks, 'webhook')}"
        )


@dataclass(frozen=True, kw_only=True)
class MadeApiUser(Activity):
    user: User

    def says(self) -> str:
        return f"made {user(self.user)} an API user: its password is deleted"


@dataclass(frozen=True, kw_only=True)
class UiSignInAllowed(Activity):
    """The host gave an API user its UI sign-in back."""

    user: User

    def says(self) -> str:
        return f"let {user(self.user)} sign in to the UI again"


@dataclass(frozen=True, kw_only=True)
class PasswordChanged(Activity):
    def says(self) -> str:
        return "changed its password"


@dataclass(frozen=True, kw_only=True)
class PasswordSet(Activity):
    """Another user's password, to be changed at the next sign-in: one the
    actor typed, or a one-time password the service made."""

    user: User
    one_time: bool

    def says(self) -> str:
        if self.one_time:
            return f"made a one-time password for {user(self.user)}"
        return f"set the password of {user(self.user)}"
