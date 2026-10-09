"""API tokens of a user: what each is, and a new one's secret, shown
once."""

from __future__ import annotations

from dataclasses import dataclass
from datetime import datetime

from .secrets import Secret


@dataclass(frozen=True)
class Token:
    """A token of a user, never its secret. ``state`` is ``active``,
    ``expired`` or ``revoked``."""

    id: str
    user_id: str
    name: str
    state: str
    created_at: datetime
    expires_at: datetime | None
    last_used_at: datetime | None
    revoked_at: datetime | None


@dataclass(frozen=True)
class NewToken:
    """A token just made, and its secret for the bearer header, shown this
    once: only its hash is kept."""

    token: Token
    secret: Secret
