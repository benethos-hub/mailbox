"""Users, passwords, tokens, roles (docs/LOGGING.md 5.3)."""

from __future__ import annotations

from dataclasses import dataclass
from datetime import datetime
from typing import ClassVar

from ....common.clock import log_time
from ....data.models import User
from ..base import Activity, plural, user


@dataclass(frozen=True, kw_only=True)
class UserCreated(Activity):
    name: ClassVar[str] = "created"

    user: User

    def says(self) -> str:
        roles = ", ".join(self.user.roles) or "none"
        sign_in = "the UI and the API" if self.user.ui_sign_in else "the API"
        return (
            f"created user {user(self.user)}: roles {roles}, "
            f"{plural(len(self.user.grants), 'grant')}, signs in to {sign_in}"
        )


@dataclass(frozen=True, kw_only=True)
class UserChanged(Activity):
    name: ClassVar[str] = "changed"

    user: User
    # The names of the fields that changed: name, roles, grants, ...
    changed: tuple[str, ...]

    def says(self) -> str:
        return f"changed user {user(self.user)}: {', '.join(self.changed)}"


@dataclass(frozen=True, kw_only=True)
class UserDeleted(Activity):
    name: ClassVar[str] = "deleted"

    user: User
    webhooks: int

    def says(self) -> str:
        return (
            f"deleted user {user(self.user)} and its {plural(self.webhooks, 'webhook')}"
        )


@dataclass(frozen=True, kw_only=True)
class MadeApiUser(Activity):
    name: ClassVar[str] = "made_api_user"

    user: User

    def says(self) -> str:
        return f"made {user(self.user)} an API user: its password is deleted"


@dataclass(frozen=True, kw_only=True)
class UiSignInAllowed(Activity):
    """The host gave an API user its UI sign-in back."""

    name: ClassVar[str] = "sign_in_allowed"

    user: User

    def says(self) -> str:
        return f"let {user(self.user)} sign in to the UI again"


@dataclass(frozen=True, kw_only=True)
class PasswordChanged(Activity):
    name: ClassVar[str] = "password_changed"

    def says(self) -> str:
        return "changed its password"


@dataclass(frozen=True, kw_only=True)
class PasswordSet(Activity):
    """Another user's password, to be changed at the next sign-in: one the
    actor typed, or a one-time password the service made."""

    name: ClassVar[str] = "password_set"

    user: User
    one_time: bool

    def says(self) -> str:
        if self.one_time:
            return f"made a one-time password for {user(self.user)}"
        return f"set the password of {user(self.user)}"


@dataclass(frozen=True, kw_only=True)
class TokenIssued(Activity):
    name: ClassVar[str] = "token_issued"

    token_id: str
    token_name: str
    user: User
    expires_at: datetime | None

    def says(self) -> str:
        expires = (
            f"it expires {log_time(self.expires_at)}"
            if self.expires_at is not None
            else "it does not expire"
        )
        return (
            f"issued token {self.token_name} ({self.token_id}) for "
            f"{user(self.user)}, {expires}"
        )


@dataclass(frozen=True, kw_only=True)
class TokenRevoked(Activity):
    name: ClassVar[str] = "token_revoked"

    token_id: str
    token_name: str
    user: User

    def says(self) -> str:
        return f"revoked token {self.token_name} ({self.token_id}) of {user(self.user)}"


@dataclass(frozen=True, kw_only=True)
class RoleCreated(Activity):
    name: ClassVar[str] = "role_created"

    role_id: str
    grants: int

    def says(self) -> str:
        return f"created role {self.role_id} with {plural(self.grants, 'grant')}"


@dataclass(frozen=True, kw_only=True)
class RoleReplaced(Activity):
    name: ClassVar[str] = "role_replaced"

    role_id: str
    grants: int

    def says(self) -> str:
        return (
            f"replaced role {self.role_id}: it has {plural(self.grants, 'grant')} now"
        )


@dataclass(frozen=True, kw_only=True)
class RoleDeleted(Activity):
    name: ClassVar[str] = "role_deleted"

    role_id: str

    def says(self) -> str:
        return f"deleted role {self.role_id}"
