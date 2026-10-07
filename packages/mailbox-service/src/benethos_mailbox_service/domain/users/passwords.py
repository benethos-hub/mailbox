"""The passwords of users who sign in to the UI: one's own changed with
the current one, another's set within the caller's rights, a one-time
password made by the service."""

from __future__ import annotations

import secrets
from datetime import datetime

from ...data.models import User
from ...data.storage import UserRepository
from ...errors import BadRequestError, ConflictError, NotFoundError
from ..activity import HOST, ActivityLog, Actor
from ..activity import users as said
from ..auth import AuthService, SignInState
from ..rights import Access
from .rules import UserRules

# A one-time password of 18 random bytes: 24 characters, 144 bits.
ONE_TIME_BYTES = 18


class PasswordService:
    def __init__(
        self,
        users: UserRepository,
        auth: AuthService,
        rules: UserRules,
        activity: ActivityLog,
    ) -> None:
        self._users = users
        self._auth = auth
        self._rules = rules
        self._activity = activity

    def sign_in_state(self, user: User) -> SignInState:
        """Whether the user has a password, must change it, and when it
        last signed in to the UI. For a user the caller has read already,
        as ``token_state`` is for a token."""
        return self._auth.sign_in_state(user.id)

    async def change_password(self, access: Access, current: str, new: str) -> datetime:
        """The caller's own password, with the current one. Returns the new
        stamp, which keeps the caller's session and ends its others."""
        user = self._users.get(access.user_id)
        if not await self._auth.passwords.matches(user.id, current):
            raise BadRequestError("the current password is not right")
        if new == current:
            raise BadRequestError("the new password is the current one")
        hashed = await self._auth.passwords.hashed(new, user.name)
        with self._activity.atomic():
            stored = self._auth.passwords.keep(user.id, hashed, must_change=False)
            self._activity.record(said.PasswordChanged(by=Actor.of(access)))
        return stored.updated_at

    async def set_password(
        self, access: Access, user_id: str, new: str | None = None
    ) -> str | None:
        """Another user's password, within the caller's rights: whoever sets
        it can sign in as that user. Without ``new`` the service makes a
        one-time password and returns it, to be shown once. Either must be
        changed at the next sign-in."""
        user = self._settable(access, user_id)
        password = await self._force(user, new, Actor.of(access))
        return password if new is None else None

    async def one_time_password(self, access: Access, user_id: str) -> str:
        """``set_password`` without a password: the one the service made."""
        user = self._settable(access, user_id)
        return await self._force(user, None, Actor.of(access))

    async def reset_password(self, name: str) -> tuple[User, str]:
        """A new one-time password for the user of this name, to be changed
        at the next sign-in. For the command line on the host only, when
        nobody who could set it can sign in: it checks no caller. An API
        user may sign in to the UI from now on."""
        user = self._auth.user_named(name)
        if user is None:
            raise NotFoundError(f"no user is named {name}")
        if not user.ui_sign_in:
            user = user.model_copy(update={"ui_sign_in": True})
            with self._activity.atomic():
                self._users.save(user)
                self._activity.record(said.UiSignInAllowed(by=HOST, user=user))
        return user, await self.one_time(user)

    async def one_time(self, user: User) -> str:
        """A one-time password the host set, e.g. for a new administrator."""
        return await self._force(user, None, HOST)

    async def _force(self, user: User, new: str | None, by: Actor) -> str:
        """A password the user must change at its next sign-in: ``new``, or
        without it a random one, to be shown once. Returns the one set."""
        password = secrets.token_urlsafe(ONE_TIME_BYTES) if new is None else new
        hashed = await self._auth.passwords.hashed(password, user.name)
        with self._activity.atomic():
            self._auth.passwords.keep(user.id, hashed, must_change=True)
            self._activity.record(
                said.PasswordSet(by=by, user=user, one_time=new is None)
            )
        return password

    def _settable(self, access: Access, user_id: str) -> User:
        """The user whose password the caller may set."""
        user = self._rules.managed(access, "set_password", user_id)
        if user_id == access.user_id:
            raise ConflictError("change your own password with the current one")
        if not user.ui_sign_in:
            raise ConflictError(
                f"{user.name} is an API user: switch on its UI sign-in first"
            )
        return user
