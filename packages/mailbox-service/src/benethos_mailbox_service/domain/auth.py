"""Who is calling: credentials to an ``Access``.

The web layer hands over what the caller presented, this module decides
whether it is valid and whose rights it carries.
"""

from __future__ import annotations

import hashlib
import logging
import secrets
import string
from collections.abc import Callable
from dataclasses import dataclass
from datetime import datetime, timedelta
from typing import Literal

from ..common.clock import utc_now
from ..common.ids import new_id
from ..data.models import ApiToken, User
from ..data.storage import (
    InMemoryPasswordRepository,
    RoleRepository,
    TokenRepository,
    UserRepository,
)
from ..errors import (
    BadRequestError,
    NotFoundError,
    SetupRequiredError,
    UnauthorizedError,
)
from .access import Access
from .passwords import MAX_LENGTH, Passwords
from .throttle import SignInThrottle

log = logging.getLogger(__name__)

TOKEN_PREFIX = "mbx_"
_ALPHABET = string.ascii_letters + string.digits
# 64 characters of base62 carry a little over 380 bits.
_TOKEN_LENGTH = 64

TokenState = Literal["active", "expired", "revoked"]

# A user name that fails this often in the window waits this long, from
# any address: slower guessing at one account from many addresses, and
# never a long lockout of its owner.
NAME_LIMIT = 10
NAME_WINDOW = timedelta(minutes=15)
NAME_LOCKOUT = timedelta(minutes=1)
WRONG = "wrong user name or password"
MAX_NAME = 200


@dataclass(frozen=True)
class SignedIn:
    """Who signed in with a password, for a session of the UI."""

    user_id: str
    # The password was set by someone else: it must be changed first.
    must_change: bool
    # When the password was set. The session keeps it and ends once the
    # password changes.
    stamp: datetime
    # The sign-in before this one, to show the user.
    previous: datetime | None = None


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
        clock: Callable[[], datetime] = utc_now,
        throttle: SignInThrottle | None = None,
        passwords: Passwords | None = None,
    ) -> None:
        self._users = users
        self._roles = roles
        self._tokens = tokens
        self._clock = clock
        self._throttle = throttle or SignInThrottle(clock=clock)
        self._names = SignInThrottle(
            limit=NAME_LIMIT, window=NAME_WINDOW, lockout=NAME_LOCKOUT, clock=clock
        )
        self.passwords = passwords or Passwords(InMemoryPasswordRepository())

    async def sign_in(self, name: str, password: str, *, source: str) -> SignedIn:
        """The user behind a name and a password. A wrong name, a wrong
        password and a disabled user answer alike, in the same time. The
        source and the name are slowed down after failures."""
        if self._users.count() == 0:
            raise SetupRequiredError(
                "no user exists: run `benethos-mailbox-service users create-admin`"
            )
        key = name.strip().casefold()[:MAX_NAME]
        self._throttle.check(source)
        self._names.check(key)
        if len(password) > MAX_LENGTH or len(name) > MAX_NAME:
            # No password is that long: not worth a hash.
            self._throttle.failed(source)
            self._names.failed(key)
            raise UnauthorizedError(WRONG)
        user = self.user_named(name)
        matched = await self.passwords.matches(user.id if user else None, password)
        stored = self.passwords.stored(user.id) if user is not None else None
        if (
            not matched
            or user is None
            or user.disabled
            or not user.ui_sign_in
            or stored is None
        ):
            self._throttle.failed(source)
            self._names.failed(key)
            # The name only when it is a user's: a password typed into the
            # name field must not end up in the log.
            who = f"{user.name} ({user.id})" if user is not None else "an unknown name"
            why = " (an API user)" if user is not None and not user.ui_sign_in else ""
            log.warning("failed sign-in to the UI as %s%s from %s", who, why, source)
            raise UnauthorizedError(WRONG)
        self._throttle.succeeded(source)
        self._names.succeeded(key)
        log.info("sign-in to the UI as %s (%s) from %s", user.name, user.id, source)
        previous = self.passwords.signed_in(user.id)
        return SignedIn(user.id, stored.must_change, stored.updated_at, previous)

    async def confirm(self, access: Access, password: str) -> None:
        """The signed-in user's password once more, before a step that
        hands out much. A wrong one counts against the user's name as a
        failed sign-in does."""
        user = self._users.get(access.user_id)
        key = user.name.casefold()[:MAX_NAME]
        self._names.check(key)
        matched = len(password) <= MAX_LENGTH and await self.passwords.matches(
            user.id, password
        )
        if not matched:
            self._names.failed(key)
            log.warning(
                "a wrong password to confirm a step: %s (%s)", user.name, user.id
            )
            raise BadRequestError("the password is not right")

    def session_access(self, user_id: str, stamp: datetime) -> Access:
        """What the user of a UI session may do now. Raises when the user
        is gone or disabled, or its password changed since the sign-in."""
        try:
            user = self._users.get(user_id)
        except NotFoundError:
            raise UnauthorizedError("the user no longer exists") from None
        if user.disabled:
            raise UnauthorizedError("user is disabled")
        if not user.ui_sign_in:
            raise UnauthorizedError("the user signs in to the API only")
        stored = self.passwords.stored(user_id)
        if stored is None or stored.updated_at != stamp:
            raise UnauthorizedError("the password changed: sign in again")
        roles = {role.id: role for role in self._roles.list()}
        return Access.for_user(user, roles)

    def user_named(self, name: str) -> User | None:
        """The user with this name, regardless of case."""
        wanted = name.strip().casefold()
        return next(
            (u for u in self._users.list() if u.name.casefold() == wanted), None
        )

    def authenticate(
        self, presented: str | None, *, source: str | None = None
    ) -> Access:
        """Whose rights ``presented`` carries. With a ``source``, the client
        address of a sign-in, guessing is slowed down: a source that failed
        too often is locked out for a while (``RateLimitedError``), before
        the credential is looked at. A request that carries a session the
        service made itself passes no source."""
        if self._users.count() == 0:
            raise SetupRequiredError(
                "no user exists: run `benethos-mailbox-service users create-admin`"
            )
        if not presented:
            raise UnauthorizedError("missing bearer token")
        if source is not None:
            self._throttle.check(source)
        try:
            access = self._access_for_token(presented)
        except UnauthorizedError:
            if source is not None:
                self._throttle.failed(source)
            raise
        if source is not None:
            self._throttle.succeeded(source)
        return access

    def access_of(self, user_id: str) -> Access | None:
        """What a user may do now, for work done on its behalf outside a
        request, such as a webhook. None for a user that is gone or
        disabled."""
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
        self._tokens.touch(token.id, now)
        roles = {role.id: role for role in self._roles.list()}
        return Access.for_user(user, roles, token.id)
