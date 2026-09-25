"""Who is calling: credentials to an ``Access``.

The web layer hands over what the caller presented, this module decides
whether it is valid and whose rights it carries.
"""

from __future__ import annotations

import hashlib
import secrets
import string
from collections.abc import Callable
from datetime import datetime
from typing import Literal

from ..common.clock import utc_now
from ..common.ids import new_id
from ..data.models import ApiToken
from ..data.storage import RoleRepository, TokenRepository, UserRepository
from ..errors import (
    BadRequestError,
    NotFoundError,
    SetupRequiredError,
    UnauthorizedError,
)
from .access import Access
from .throttle import SignInThrottle

TOKEN_PREFIX = "mbx_"
_ALPHABET = string.ascii_letters + string.digits
# 64 characters of base62 carry a little over 380 bits.
_TOKEN_LENGTH = 64

ADMIN_KEY_USER_ID = "usr_admin_key"

TokenState = Literal["active", "expired", "revoked"]


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
        clock: Callable[[], datetime] = utc_now,
        throttle: SignInThrottle | None = None,
    ) -> None:
        self._users = users
        self._roles = roles
        self._tokens = tokens
        self._admin_key = admin_key or None
        self._clock = clock
        self._throttle = throttle or SignInThrottle(clock=clock)

    def authenticate(
        self, presented: str | None, *, source: str | None = None
    ) -> Access:
        """Whose rights ``presented`` carries. With a ``source``, the client
        address of a sign-in, guessing is slowed down: a source that failed
        too often is locked out for a while (``RateLimitedError``), before
        the credential is looked at. A request that carries a session the
        service made itself passes no source."""
        if self._admin_key is None and self._users.count() == 0:
            raise SetupRequiredError(
                "no user exists and MAILBOX_SERVICE_KEY is not set: "
                "run `benethos-mailbox-service users create-admin`"
            )
        if not presented:
            raise UnauthorizedError("missing bearer token")
        if source is not None:
            self._throttle.check(source)
        try:
            access = self._authenticate(presented)
        except UnauthorizedError:
            if source is not None:
                self._throttle.failed(source)
            raise
        if source is not None:
            self._throttle.succeeded(source)
        return access

    def _authenticate(self, presented: str) -> Access:
        if self._admin_key is not None and secrets.compare_digest(
            presented.encode(), self._admin_key.encode()
        ):
            return Access.admin(ADMIN_KEY_USER_ID, "admin key")
        return self._access_for_token(presented)

    def access_of(self, user_id: str) -> Access | None:
        """What a user may do now, for work done on its behalf outside a
        request, such as a webhook. None for a user that is gone or
        disabled, and for the admin key once it is no longer set."""
        if user_id == ADMIN_KEY_USER_ID:
            if self._admin_key is None:
                return None
            return Access.admin(ADMIN_KEY_USER_ID, "admin key")
        try:
            user = self._users.get(user_id)
        except NotFoundError:
            return None
        if user.disabled:
            return None
        roles = {role.id: role for role in self._roles.list()}
        return Access.for_user(user, roles)

    def issue_token(
        self, user_id: str, name: str, expires_at: datetime | None = None
    ) -> tuple[ApiToken, str]:
        """A new token for a user. The plain token is returned once only."""
        self._users.get(user_id)
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

    def revoke_token(self, token_id: str) -> ApiToken:
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

    def _access_for_token(self, presented: str) -> Access:
        token = self._tokens.find_by_hash(hash_token(presented))
        if token is None or self.state_of(token) == "revoked":
            raise UnauthorizedError("invalid or revoked token")
        if self.state_of(token) == "expired":
            raise UnauthorizedError("token expired")
        now = self._clock()
        try:
            user = self._users.get(token.user_id)
        except NotFoundError:
            raise UnauthorizedError("invalid or revoked token") from None
        if user.disabled:
            raise UnauthorizedError("user is disabled")
        self._tokens.save(token.model_copy(update={"last_used_at": now}))
        roles = {role.id: role for role in self._roles.list()}
        return Access.for_user(user, roles, token.id)
