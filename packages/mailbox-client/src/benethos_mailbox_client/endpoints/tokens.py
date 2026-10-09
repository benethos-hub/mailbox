"""The API tokens of a user: listed, made and revoked, read into
``Token`` and ``NewToken``."""

from __future__ import annotations

from datetime import datetime
from typing import Any

from ..calls import Call, given, nothing, path
from ..models import NewToken, Secret, Token
from .readings import maybe_time, time


def list_tokens(user_id: str) -> Call[list[Token]]:
    return Call(
        "GET", path("users", user_id, "tokens"), lambda found: [token(t) for t in found]
    )


def create_token(
    user_id: str, name: str, expires_at: datetime | None = None
) -> Call[NewToken]:
    """A token for the API and the MCP server, valid until ``expires_at``,
    a time with its zone, or without it for good. Its secret comes back
    this once."""
    return Call(
        "POST",
        path("users", user_id, "tokens"),
        lambda found: NewToken(token=token(found), secret=Secret(str(found["token"]))),
        json=given(
            {"name": name, "expires_at": expires_at.isoformat() if expires_at else None}
        ),
    )


def revoke_token(user_id: str, token_id: str) -> Call[None]:
    """Whoever uses the token is locked out at once."""
    return Call("DELETE", path("users", user_id, "tokens", token_id), nothing)


def token(item: dict[str, Any]) -> Token:
    return Token(
        id=str(item["id"]),
        user_id=str(item["user_id"]),
        name=str(item["name"]),
        state=str(item["state"]),
        created_at=time(item["created_at"]),
        expires_at=maybe_time(item.get("expires_at")),
        last_used_at=maybe_time(item.get("last_used_at")),
        revoked_at=maybe_time(item.get("revoked_at")),
    )
