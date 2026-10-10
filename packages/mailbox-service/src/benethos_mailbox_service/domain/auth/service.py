"""Who is calling: credentials to an ``Access``.

The web layer hands over what the caller presented, this module decides
whether it is valid and whose rights it carries. The API tokens
themselves are ``tokens``.
"""

from __future__ import annotations

from collections.abc import Callable
from datetime import datetime, timedelta

from ...common.clock import utc_now
from ...data.models import ApiToken, User
from ...data.storage import RoleRepository, TokenRepository, UserRepository
from ...errors import (
    BadRequestError,
    NotFoundError,
    SetupRequiredError,
    UnauthorizedError,
)
from ..activity import PASSWORD, SERVICE, ActivityLog, Actor, someone
from ..activity import auth as said
from ..activity import users as users_said
from ..rights import Access
from .factors import SecondFactors, Taken
from .passwords import MAX_LENGTH, Passwords
from .signin import SignedIn, SignInState
from .throttle import SignInThrottle
from .tokens import ApiTokens, IssuedToken, TokenState

# A user name that fails this often in the window waits this long, from
# any address: slower guessing at one account from many addresses, and
# never a long lockout of its owner.
NAME_LIMIT = 10
NAME_WINDOW = timedelta(minutes=15)
NAME_LOCKOUT = timedelta(minutes=1)
WRONG = "wrong user name or password"
WRONG_CODE = "the code is not right"
MAX_NAME = 200
# Longer than any code or recovery code, with room for spaces.
MAX_CODE = 40
# How the audit names a sign-in with a second factor.
WITH_FACTOR = {"totp": "password+totp", "recovery": "password+recovery"}


class AuthService:
    def __init__(
        self,
        users: UserRepository,
        roles: RoleRepository,
        tokens: TokenRepository,
        passwords: Passwords,
        clock: Callable[[], datetime] = utc_now,
        throttle: SignInThrottle | None = None,
        names: SignInThrottle | None = None,
        activity: ActivityLog | None = None,
        factors: SecondFactors | None = None,
    ) -> None:
        """``throttle`` slows down a client address that fails to sign
        in, ``names`` a user name, whatever the address. Without
        ``factors`` no user has a second factor."""
        self._users = users
        self._roles = roles
        self._clock = clock
        self._throttle = throttle or SignInThrottle(clock=clock)
        self._names = names or SignInThrottle(
            limit=NAME_LIMIT, window=NAME_WINDOW, lockout=NAME_LOCKOUT, clock=clock
        )
        self.passwords = passwords
        self.factors = factors
        self.activity = activity or ActivityLog(clock)
        self._api_tokens = ApiTokens(tokens, users, clock, self.activity)
        # The unknown rights already logged, per user and names.
        self._told_unknown: set[tuple[str, frozenset[str]]] = set()

    async def sign_in(self, name: str, password: str, *, source: str) -> SignedIn:
        """The user behind a name and a password. A wrong name, a wrong
        password and a disabled user answer alike, in the same time. The
        source and the name are slowed down after failures. A user with a
        second factor is not signed in yet: ``needs_code``, and
        ``sign_in_with_code`` next."""
        self._require_users()
        key = _name_key(name)
        self._check_source(source)
        self._names.check(key)
        if len(password) > MAX_LENGTH or len(name) > MAX_NAME:
            # No password is that long: not worth a hash.
            self._failed_source(source)
            self._failed_name(key, None, someone(source))
            raise UnauthorizedError(WRONG)
        user = self.user_named(name)
        matched = await self.passwords.matches(user.id if user else None, password)
        stored = self.passwords.stored(user.id) if user is not None else None
        refused = _refused(user, matched, stored is not None)
        if user is None or stored is None or refused is not None:
            self._failed_source(source)
            self._failed_name(key, user, someone(source))
            # The name only when it is a user's: a password typed into the
            # name field must not end up in the log.
            self.activity.record(
                said.UiSignInFailed(
                    by=someone(source),
                    user=user,
                    reason=refused or "the name is no user's",
                )
            )
            raise UnauthorizedError(WRONG)
        if self.factor_stamp(user.id) is not None:
            # The failures counted so far stay until the code is right.
            return SignedIn(
                user.id, stored.must_change, stored.updated_at, needs_code=True
            )
        return self._signed_in(user, key, source, PASSWORD)

    def sign_in_with_code(self, user_id: str, code: str, *, source: str) -> SignedIn:
        """The second step of a sign-in, after the password: a code of the
        user's app, or one of its recovery codes. A wrong one counts as a
        failed sign-in for the source and the name."""
        self._check_source(source)
        user = self._live_user(user_id)
        key = _name_key(user.name)
        self._names.check(key)
        taken = (
            self.factors.check(user.id, code)
            if self.factors is not None and len(code) <= MAX_CODE and user.ui_sign_in
            else None
        )
        if taken is None:
            self._failed_source(source)
            self._failed_name(key, user, someone(source))
            self.activity.record(said.CodeFailed(by=someone(source), user=user))
            raise UnauthorizedError(WRONG_CODE)
        return self._signed_in(user, key, source, PASSWORD, taken)

    def _signed_in(
        self,
        user: User,
        key: str,
        source: str,
        credential: str,
        taken: Taken | None = None,
    ) -> SignedIn:
        """A sign-in that passed every step: the brakes cleared, the time
        stored, the audit told."""
        stored = self.passwords.stored(user.id)
        if stored is None:
            raise UnauthorizedError(WRONG)
        self._throttle.succeeded(source)
        self._names.succeeded(key)
        if taken is not None:
            credential = WITH_FACTOR[taken.kind]
        by = Actor.signed_in(user.name, user.id, source, credential)
        with self.activity.atomic():
            previous = self.passwords.signed_in(user.id)
            device = taken.device if taken is not None else None
            self.activity.record(said.UiSignIn(by=by, device=device))
            if taken is not None and taken.kind == "recovery" and self.factors:
                left = self.factors.codes_left(user.id)
                self.activity.record(said.RecoveryCodeUsed(by=by, left=left))
        return SignedIn(
            user.id,
            stored.must_change,
            stored.updated_at,
            previous,
            factor=self.factor_stamp(user.id),
        )

    def factor_stamp(self, user_id: str) -> str | None:
        """Which devices of a second factor the user has, None without
        one."""
        return self.factors.stamp(user_id) if self.factors is not None else None

    async def confirm(self, access: Access, password: str) -> None:
        """The signed-in user's password once more, before a step that
        hands out much. A wrong one counts against the user's name and the
        client address as a failed sign-in does."""
        user = self._users.get(access.user_id)
        key = _name_key(user.name)
        self._check_caller(access, key)
        matched = len(password) <= MAX_LENGTH and await self.passwords.matches(
            user.id, password
        )
        if not matched:
            self._failed_caller(access, key, user)
            self.activity.record(said.ConfirmFailed(by=Actor.of(access)))
            raise BadRequestError("the password is not right")

    def confirm_code(self, access: Access, code: str) -> None:
        """A code of the signed-in user's second factor, before a step
        that takes it away. A wrong one counts against the user's name and
        the client address as a wrong password does."""
        user = self._users.get(access.user_id)
        key = _name_key(user.name)
        self._check_caller(access, key)
        right = (
            self.factors is not None
            and len(code) <= MAX_CODE
            and self.factors.check(user.id, code) is not None
        )
        if not right:
            self._failed_caller(access, key, user)
            self.activity.record(said.ConfirmFailed(by=Actor.of(access), what="code"))
            raise BadRequestError(WRONG_CODE)

    def _check_caller(self, access: Access, key: str) -> None:
        """``RateLimitedError`` while the caller's address or name is
        locked out."""
        if access.source is not None:
            self._check_source(access.source)
        self._names.check(key)

    def _failed_caller(self, access: Access, key: str, user: User) -> None:
        """A wrong confirmation, counted for the address and the name."""
        if access.source is not None:
            self._failed_source(access.source)
        self._failed_name(key, user, Actor.of(access))

    def session_access(
        self,
        user_id: str,
        stamp: datetime,
        *,
        factor: str | None = None,
        source: str | None = None,
    ) -> Access:
        """What the user of a UI session may do now. Raises when the user
        is gone or disabled, or its password or its second factor changed
        since the sign-in: ``stamp`` and ``factor`` are those of the
        sign-in. ``source`` is the client address of the request."""
        user = self._live_user(user_id)
        if not user.ui_sign_in:
            raise UnauthorizedError("the user signs in to the API only")
        stored = self.passwords.stored(user_id)
        if stored is None or stored.updated_at != stamp:
            raise UnauthorizedError("the password changed: sign in again")
        if self.factor_stamp(user_id) != factor:
            raise UnauthorizedError("the second factor changed: sign in again")
        return self._access(user, source=source)

    def user_named(self, name: str) -> User | None:
        """The user with this name, regardless of case."""
        wanted = name.strip().casefold()
        return next(
            (u for u in self._users.list() if u.name.strip().casefold() == wanted),
            None,
        )

    def authenticate(
        self, presented: str | None, *, source: str | None = None
    ) -> Access:
        """Whose rights ``presented`` carries. With a ``source``, the client
        address of the request, guessing is slowed down: a wrong token
        counts a failure of the source, and a source that failed too often
        is refused (``RateLimitedError``) instead of told that its token
        is wrong. A valid token passes whatever its source did, and clears
        nothing: a token cannot be guessed, and a lockout of an address
        many clients share must not stop the ones with a valid token. A
        request that carries a session the service made itself passes no
        source."""
        self._require_users()
        if not presented:
            raise UnauthorizedError("missing bearer token")
        try:
            return self._access_for_token(presented, source)
        except UnauthorizedError:
            if source is not None:
                self._check_source(source)
                self._failed_source(source)
            raise

    def access_of(self, user_id: str) -> Access | None:
        """What a user may do now, for work done on its behalf outside a
        request, such as a webhook. None for a user that is gone or
        disabled."""
        try:
            return self._access(self._live_user(user_id))
        except UnauthorizedError:
            return None

    def issue_token(
        self, user_id: str, name: str, expires_at: datetime | None = None
    ) -> IssuedToken:
        """A new token for a user. The plain token is returned once only."""
        return self._api_tokens.issue(user_id, name, expires_at)

    def revoke_token(self, token_id: str) -> ApiToken:
        return self._api_tokens.revoke(token_id)

    def state_of(self, token: ApiToken) -> TokenState:
        return self._api_tokens.state_of(token)

    def sign_in_state(self, user_id: str) -> SignInState:
        stored = self.passwords.stored(user_id)
        factor = self.factor_stamp(user_id) is not None
        if stored is None:
            return SignInState(False, False, None, factor)
        return SignInState(True, stored.must_change, stored.last_sign_in_at, factor)

    def _live_user(self, user_id: str) -> User:
        """The user, ``UnauthorizedError`` when it is gone or disabled."""
        try:
            user = self._users.get(user_id)
        except NotFoundError:
            raise UnauthorizedError("the user no longer exists") from None
        if user.disabled:
            raise UnauthorizedError("user is disabled")
        return user

    def _access_for_token(self, presented: str, source: str | None) -> Access:
        token, user = self._api_tokens.presented(presented, source)
        return self._access(user, token, source)

    def _check_source(self, source: str) -> None:
        """``RateLimitedError`` while the source is locked out. A lockout
        that ran out is logged here, at the next attempt."""
        if self._throttle.check(source):
            self.activity.record(said.LockoutEnded(by=someone(source)))

    def _failed_source(self, source: str) -> None:
        if self._throttle.failed(source):
            minutes = int(self._throttle.lockout.total_seconds() // 60)
            self.activity.record(
                said.SourceLockedOut(by=someone(source), minutes=minutes)
            )

    def _failed_name(self, key: str, user: User | None, by: Actor) -> None:
        """The name as typed is logged only as the user it names."""
        if self._names.failed(key):
            seconds = int(self._names.lockout.total_seconds())
            self.activity.record(said.NameBraked(by=by, user=user, seconds=seconds))

    def sign_out(self, access: Access) -> None:
        """The session of the UI ends. The web layer drops it, this logs it."""
        self.activity.record(said.SignedOut(by=Actor.of(access)))

    def _access(
        self, user: User, token: ApiToken | None = None, source: str | None = None
    ) -> Access:
        """What the user may do now, through its grants and its roles."""
        roles = {role.id: role for role in self._roles.list()}
        access = Access.for_user(
            user,
            roles,
            token.id if token is not None else None,
            credential_name=token.name if token is not None else None,
            source=source,
            now=self._clock(),
        )
        told = (user.id, access.unknown)
        if access.unknown and told not in self._told_unknown:
            # Once per user and names, not on every request.
            self._told_unknown.add(told)
            self.activity.record(
                users_said.UnknownRights(
                    by=SERVICE, user=user, names=tuple(sorted(access.unknown))
                )
            )
        return access

    def _require_users(self) -> None:
        if self._users.count() == 0:
            raise SetupRequiredError(
                "no user exists: run `benethos-mailbox-service users create-admin`"
            )


def _name_key(name: str) -> str:
    """A name as the throttle counts it: regardless of case and of the
    spaces around it, and not longer than a name can be."""
    return name.strip().casefold()[:MAX_NAME]


def _refused(user: User | None, matched: bool, has_password: bool) -> str | None:
    """Why a sign-in of a known user fails, for the log. None when it
    passes."""
    if user is None:
        return None
    if user.disabled:
        return "the user is disabled"
    if not user.ui_sign_in:
        return "an API user"
    if not has_password:
        return "the user has no password"
    if not matched:
        return "a wrong password"
    return None
