"""API tokens: issued, revoked, their state, and the one a caller
presented checked.

A token is handed out once and kept as its digest only. What the token's
user may do is ``AuthService``'s to decide.
"""

from __future__ import annotations

import secrets
import string
from collections.abc import Callable
from datetime import datetime
from typing import Literal

from ...common.secret import digest, new_id
from ...data.models import ApiToken, User
from ...data.storage import TokenRepository, UserRepository
from ...errors import BadRequestError, NotFoundError, UnauthorizedError
from ..activity import ActivityLog, someone
from ..activity import auth as said

TOKEN_PREFIX = "mbx_"
_ALPHABET = string.ascii_letters + string.digits
# 64 characters of base62 carry a little over 380 bits.
_TOKEN_LENGTH = 64

TokenState = Literal["active", "expired", "revoked"]


def hash_token(token: str) -> str:
    return digest(token)


def new_token() -> str:
    return TOKEN_PREFIX + "".join(
        secrets.choice(_ALPHABET) for _ in range(_TOKEN_LENGTH)
    )


class ApiTokens:
    """The tokens of the repository, judged by ``clock``. A token refused
    for its state or its user is told to ``activity``."""

    def __init__(
        self,
        tokens: TokenRepository,
        users: UserRepository,
        clock: Callable[[], datetime],
        activity: ActivityLog,
    ) -> None:
        self._tokens = tokens
        self._users = users
        self._clock = clock
        self._activity = activity

    def issue(
        self, user_id: str, name: str, expires_at: datetime | None = None
    ) -> tuple[ApiToken, str]:
        """A new token for a user. The plain token is returned once only."""
        self._users.get(user_id)
        if expires_at is not None and expires_at.utcoffset() is None:
            raise BadRequestError("expires_at needs a time zone")
        if expires_at is not None and expires_at <= self._clock():
            raise BadRequestError("the token would be expired already")
        plain = new_token()
        token = ApiToken(
            id=new_id("tok"),
            user_id=user_id,
            name=name,
            token_hash=hash_token(plain),
            created_at=self._clock(),
            expires_at=expires_at,
        )
        self._tokens.save(token)
        return token, plain

    def revoke(self, token_id: str) -> ApiToken:
        token = self._tokens.get(token_id)
        if token.revoked_at is None:
            token = token.model_copy(update={"revoked_at": self._clock()})
            self._tokens.save(token)
        return token

    def state_of(self, token: ApiToken) -> TokenState:
        if token.revoked_at is not None:
            return "revoked"
        if token.expires_at is not None and token.expires_at <= self._clock():
            return "expired"
        return "active"

    def presented(self, presented: str, source: str | None) -> tuple[ApiToken, User]:
        """The token a caller presented and its user, the token's use
        noted. ``UnauthorizedError`` for an unknown, revoked or expired
        token, or one whose user is gone or disabled."""
        token = self._tokens.find_by_hash(hash_token(presented))
        if token is None:
            raise UnauthorizedError("invalid or revoked token")
        if self.state_of(token) == "revoked":
            self._refused(token, source, "it is revoked")
            raise UnauthorizedError("invalid or revoked token")
        if self.state_of(token) == "expired":
            self._refused(token, source, "it expired")
            raise UnauthorizedError("token expired")
        now = self._clock()
        try:
            user = self._users.get(token.user_id)
        except NotFoundError:
            raise UnauthorizedError("invalid or revoked token") from None
        if user.disabled:
            self._refused(token, source, "its user is disabled")
            raise UnauthorizedError("user is disabled")
        self._tokens.touch(token.id, now)
        return token, user

    def _refused(self, token: ApiToken, source: str | None, reason: str) -> None:
        self._activity.record(
            said.TokenRefused(
                by=someone(source),
                token_id=token.id,
                token_name=token.name,
                user_id=token.user_id,
                reason=reason,
            )
        )
