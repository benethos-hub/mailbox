"""Callers of the API: users, roles, their grants and tokens."""

from __future__ import annotations

from datetime import datetime
from typing import Annotated

from pydantic import AwareDatetime, BaseModel, Field

RECIPIENT_PATTERN = r"^(\*|\*@[^\s@*]+|[^\s@*]+@[^\s@*]+)$"


# Rights of the service, in the ``service`` list of a user or a role.
SERVICE_DESCRIPTION = (
    "Rights of the service, bound to no account: `accounts.connect`, "
    "`users.read`, `users.manage`, `webhooks.manage`, `audit`, `admin`, or "
    "single operations of them. `audit` here reads the audit of "
    "administration, in a grant the sends of accounts. `admin` is every right."
)


class Grant(BaseModel):
    """Rights on accounts: operation or group names, account ids or ``*``.
    ``recipients`` and ``max_sends_per_day`` narrow sending under this grant.
    Rights of the service belong in ``service``, not in a grant."""

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
    folders: list[Annotated[str, Field(min_length=1, max_length=200)]] | None = Field(
        default=None,
        min_length=1,
        max_length=100,
        description=(
            "Reading, writing and deleting mail only in these folders and "
            "their subfolders: a role such as `inbox`, or a folder's name or "
            "id. Moves stay among them. Deleting to the trash is allowed "
            "from them, reading the trash only when it is listed. Null: "
            "every folder."
        ),
    )
    expires_at: AwareDatetime | None = Field(
        default=None,
        description=(
            "When the grant ends, with a time zone. Null: never. An expired "
            "grant grants nothing and stays until it is removed."
        ),
    )


class User(BaseModel):
    """Someone or something that calls the API."""

    id: str
    name: str
    roles: list[str] = Field(default_factory=list)
    service: list[str] = Field(default_factory=list, description=SERVICE_DESCRIPTION)
    grants: list[Grant] = Field(default_factory=list)
    disabled: bool = False
    ui_sign_in: bool = Field(
        default=False,
        description=(
            "Whether the user may sign in to the configuration UI with a "
            "password. Without it, the user works with tokens only."
        ),
    )


class Role(BaseModel):
    """A named, reusable set of grants and service rights."""

    id: str
    service: list[str] = Field(default_factory=list, description=SERVICE_DESCRIPTION)
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
