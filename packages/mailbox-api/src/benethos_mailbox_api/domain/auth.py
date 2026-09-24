"""Who is calling: credentials to an ``Access``.

The web layer hands over what the caller presented, this module decides
whether it is valid and whose rights it carries.
"""

from __future__ import annotations

import hashlib
import secrets
import string
import uuid
from collections.abc import Callable
from datetime import UTC, datetime

from ..data.models import ApiToken
from ..data.storage import RoleRepository, TokenRepository, UserRepository
from ..errors import NotFoundError, SetupRequiredError, UnauthorizedError
from .access import Access

TOKEN_PREFIX = "mbx_"
_ALPHABET = string.ascii_letters + string.digits
# 43 characters of base62 carry a little over 256 bits.
_TOKEN_LENGTH = 43

ADMIN_KEY_USER_ID = "usr_admin_key"


def hash_token(token: str) -> str:
    return hashlib.sha256(token.encode()).hexdigest()


def new_token() -> str:
    return TOKEN_PREFIX + "".join(
        secrets.choice(_ALPHABET) for _ in range(_TOKEN_LENGTH)
    )


class AuthService:
    def __init__(
        self,
        users: UserRepository,
        roles: RoleRepository,
        tokens: TokenRepository,
        admin_key: str | None = None,
        clock: Callable[[], datetime] = lambda: datetime.now(UTC),
    ) -> None:
        self._users = users
        self._roles = roles
        self._tokens = tokens
        self._admin_key = admin_key or None
        self._clock = clock

    def authenticate(self, presented: str | None) -> Access:
        if self._admin_key is None and self._users.count() == 0:
            raise SetupRequiredError(
                "no user exists and MAILBOX_API_KEY is not set: "
                "run `benethos-mailbox-api users create-admin`"
            )
        if not presented:
            raise UnauthorizedError("missing bearer token")
        if self._admin_key is not None and secrets.compare_digest(
            presented.encode(), self._admin_key.encode()
        ):
            return Access.admin(ADMIN_KEY_USER_ID, "admin key")
        return self._access_for_token(presented)

    def issue_token(
        self, user_id: str, name: str, expires_at: datetime | None = None
    ) -> tuple[ApiToken, str]:
        """A new token for a user. The plain token is returned once only."""
        self._users.get(user_id)
        plain = new_token()
        token = ApiToken(
            id=f"tok_{uuid.uuid4().hex[:12]}",
            user_id=user_id,
            name=name,
            token_hash=hash_token(plain),
            created_at=self._clock(),
            expires_at=expires_at,
        )
        self._tokens.save(token)
        return token, plain

    def revoke_token(self, token_id: str) -> ApiToken:
        token = self._tokens.get(token_id)
        if token.revoked_at is None:
            token = token.model_copy(update={"revoked_at": self._clock()})
            self._tokens.save(token)
        return token

    def _access_for_token(self, presented: str) -> Access:
        token = self._tokens.find_by_hash(hash_token(presented))
        now = self._clock()
        if token is None or token.revoked_at is not None:
            raise UnauthorizedError("invalid or revoked token")
        if token.expires_at is not None and token.expires_at <= now:
            raise UnauthorizedError("token expired")
        try:
            user = self._users.get(token.user_id)
        except NotFoundError:
            raise UnauthorizedError("invalid or revoked token") from None
        if user.disabled:
            raise UnauthorizedError("user is disabled")
        self._tokens.save(token.model_copy(update={"last_used_at": now}))
        roles = {role.id: role for role in self._roles.list()}
        return Access.for_user(user, roles)
