"""Request and response shapes that exist only at the HTTP boundary.

The mail types themselves come from ``data.models`` and are served as they
are. What lives here is what only a caller of the API sends or receives.
"""

from __future__ import annotations

from datetime import datetime
from typing import Literal

from pydantic import BaseModel, Field, SecretStr

from ...data.models import ApiToken, Grant, ProviderType


class AccountCreate(BaseModel):
    provider: ProviderType
    email: str
    display_name: str | None = None
    settings: dict[str, str | int | bool] = Field(
        default_factory=dict,
        description="Provider-specific connection settings: host, port, ...",
    )
    credentials: dict[str, SecretStr] = Field(
        default_factory=dict,
        description="Secrets such as `password`. Stored encrypted, never returned.",
    )


class AccountUpdate(BaseModel):
    """What ``PATCH`` changes. Fields left out stay as they are."""

    display_name: str | None = None
    settings: dict[str, str | int | bool | None] = Field(
        default_factory=dict,
        description=(
            "Settings to change, merged into the current ones; `null` removes "
            "one. E.g. `smtp_host`, `smtp_port`, `smtp_security` for sending."
        ),
    )
    credentials: dict[str, SecretStr] = Field(
        default_factory=dict,
        description="New secrets such as `password`. Stored encrypted, never returned.",
    )


class DiscoveryRequest(BaseModel):
    email: str = Field(max_length=254, description="The address to be connected.")


class OAuthStart(BaseModel):
    account_id: str | None = Field(
        default=None, description="Sign this account in again. Left out: connect."
    )
    login_hint: str | None = Field(
        default=None,
        max_length=254,
        description="The address to suggest at the provider's sign-in.",
    )


class OAuthStarted(BaseModel):
    url: str = Field(description="The provider's sign-in page, for a browser.")


class ErrorDetail(BaseModel):
    code: str
    message: str


class ErrorResponse(BaseModel):
    """The body of every error the API raises itself."""

    error: ErrorDetail


class MeAccount(BaseModel):
    """An account the caller may act on."""

    id: str
    email: str
    display_name: str | None = None
    operations: list[str] = Field(description="What the caller may do on it")
    warnings: list[str] = Field(
        default_factory=list,
        description=(
            "`read_and_send_anywhere`: the caller may read mail here and send "
            "it to any address, which a mail with injected instructions could "
            "use to carry data out. Narrow sending with a grant's `recipients`."
        ),
    )


class Me(BaseModel):
    """The caller and its effective rights."""

    user_id: str
    name: str
    accounts: list[MeAccount] = Field(
        description="Every account the caller may act on, with its operations"
    )
    operations: list[str] = Field(
        description="Operations not bound to one existing account"
    )


class PermissionCatalogue(BaseModel):
    groups: dict[str, list[str]] = Field(
        description="Group name to the operations it allows"
    )


class UserCreate(BaseModel):
    name: str
    roles: list[str] = Field(default_factory=list)
    grants: list[Grant] = Field(default_factory=list)


class UserUpdate(BaseModel):
    name: str | None = None
    roles: list[str] | None = None
    grants: list[Grant] | None = None
    disabled: bool | None = None


class RoleCreate(BaseModel):
    id: str
    grants: list[Grant] = Field(default_factory=list)


class RoleReplace(BaseModel):
    grants: list[Grant] = Field(default_factory=list)


class TokenCreate(BaseModel):
    name: str
    expires_at: datetime | None = None


class TokenInfo(BaseModel):
    """A token without its secret."""

    id: str
    user_id: str
    name: str
    state: Literal["active", "expired", "revoked"] = Field(
        description="Whether the token authenticates now"
    )
    created_at: datetime
    expires_at: datetime | None = None
    last_used_at: datetime | None = None
    revoked_at: datetime | None = None

    @classmethod
    def of(cls, token: ApiToken, state: str) -> TokenInfo:
        return cls.model_validate(
            {**token.model_dump(exclude={"token_hash"}), "state": state}
        )


class TokenCreated(TokenInfo):
    token: str = Field(description="The token itself. Shown this once only.")
