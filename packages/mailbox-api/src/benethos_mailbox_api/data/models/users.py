"""Callers of the API: users, roles, their grants and tokens."""

from __future__ import annotations

from datetime import datetime

from pydantic import BaseModel, Field


class Grant(BaseModel):
    """Rights on accounts: operation or group names, account ids or ``*``."""

    accounts: list[str]
    allow: list[str]


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
