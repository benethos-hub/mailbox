"""API tokens: made, listed, never with their secret but once."""

from __future__ import annotations

from datetime import datetime
from typing import Literal

from pydantic import AwareDatetime, BaseModel, Field

from ....data.models import ApiToken


class TokenCreate(BaseModel):
    name: str
    expires_at: AwareDatetime | None = Field(
        default=None, description="With a time zone, e.g. 2026-12-31T23:59:59Z"
    )


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
