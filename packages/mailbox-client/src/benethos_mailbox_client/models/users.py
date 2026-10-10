"""Users of the service, never a secret of theirs but a password made
for one, shown once."""

from __future__ import annotations

from dataclasses import dataclass
from datetime import datetime

from .rights import Grant
from .secrets import Secret


@dataclass(frozen=True, slots=True)
class User:
    """Someone or something that calls the service. ``service`` are its
    rights bound to no account, ``ui_sign_in`` whether it may sign in to
    the UI, ``second_factor`` whether a code follows its password."""

    id: str
    name: str
    roles: tuple[str, ...]
    service: tuple[str, ...]
    grants: tuple[Grant, ...]
    disabled: bool
    ui_sign_in: bool
    has_password: bool
    must_change: bool
    last_sign_in_at: datetime | None
    second_factor: bool


@dataclass(frozen=True, slots=True)
class NewPassword:
    """A password set for a user, who must change it at its next sign-in.
    ``password`` is the one the service made, shown this once, None when
    the caller gave one."""

    password: Secret | None
    must_change: bool
