"""Callers of the API: users, roles, their grants and tokens."""

from __future__ import annotations

from datetime import datetime
from typing import Annotated

from pydantic import BaseModel, Field

RECIPIENT_PATTERN = r"^(\*|\*@[^\s@*]+|[^\s@*]+@[^\s@*]+)$"


class Grant(BaseModel):
    """Rights on accounts: operation or group names, account ids or ``*``.
    ``recipients`` and ``max_sends_per_day`` narrow sending under this grant."""

    accounts: list[str]
    allow: list[str]
    recipients: list[Annotated[str, Field(pattern=RECIPIENT_PATTERN)]] | None = Field(
        default=None,
        max_length=100,
        description=(
            "Send only to these: an address, `*@domain` or `*`. Null: to anyone."
        ),
    )
    max_sends_per_day: int | None = Field(
        default=None,
        ge=1,
        description=(
            "Mails the user may send from one account in any 24 hours under "
            "this grant. Null: no limit."
        ),
    )


class User(BaseModel):
    """Someone or something that calls the API."""

    id: str
    name: str
    roles: list[str] = Field(default_factory=list)
    grants: list[Grant] = Field(default_factory=list)
    disabled: bool = False


class Role(BaseModel):
    """A named, reusable set of grants."""

    id: str
    grants: list[Grant] = Field(default_factory=list)


class ApiToken(BaseModel):
    """An API token of a user. Only the SHA-256 hash of the token is kept."""

    id: str
    user_id: str
    name: str
    token_hash: str
    created_at: datetime
    expires_at: datetime | None = None
    last_used_at: datetime | None = None
    revoked_at: datetime | None = None
