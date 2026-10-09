"""The second factor of users who sign in to the UI: one's own set up
and removed with the password and a code, another's removed within the
caller's rights, any removed on the host (docs/AUTHENTICATION.md 4).

Setting up is for the person who scans the secret. Nobody sets one up
for another user.
"""

from __future__ import annotations

from datetime import datetime

from ...data.models import User
from ...data.secrets import totp
from ...data.storage import UserRepository
from ...errors import BadRequestError, ConflictError, NotFoundError
from ..activity import HOST, ActivityLog, Actor
from ..activity import users as said
from ..auth import AuthService, SecondFactors
from ..rights import Access
from .rules import UserRules


class SecondFactorService:
    def __init__(
        self,
        users: UserRepository,
        auth: AuthService,
        factors: SecondFactors,
        rules: UserRules,
        activity: ActivityLog,
    ) -> None:
        self._users = users
        self._auth = auth
        self._factors = factors
        self._rules = rules
        self._activity = activity

    def has(self, user_id: str) -> bool:
        return self._factors.has(user_id)

    def codes_left(self, user_id: str) -> int:
        return self._factors.codes_left(user_id)

    # --- one's own ------------------------------------------------------------

    async def begin(self, access: Access, password: str) -> bytes:
        """A new secret for the caller to scan, after its password once
        more. Nothing is stored before ``confirm``."""
        self._own_without_factor(access)
        await self._auth.confirm(access, password)
        return totp.new_secret()

    def confirm(
        self, access: Access, secret: bytes, code: str
    ) -> tuple[list[str], datetime]:
        """The factor on, once ``code`` is the secret's code now. Returns
        the recovery codes, to be shown once, and the new stamp, which
        keeps the caller's session and ends its others."""
        user = self._own_without_factor(access)
        with self._activity.atomic():
            codes = self._factors.confirm(user.id, secret, code)
            if codes is None:
                raise BadRequestError(
                    "the code is not right: check the time on the phone"
                )
            self._activity.record(said.SecondFactorSetUp(by=Actor.of(access)))
        return codes, self._stamp(user.id)

    async def renew_codes(self, access: Access, password: str) -> list[str]:
        """A new set of recovery codes for the caller, in place of the old,
        after its password once more."""
        user = self._own_with_factor(access)
        await self._auth.confirm(access, password)
        with self._activity.atomic():
            codes = self._factors.renew_codes(user.id)
            self._activity.record(said.RecoveryCodesRenewed(by=Actor.of(access)))
        return codes

    async def remove_own(self, access: Access, password: str, code: str) -> None:
        """The caller's own factor off, with its password and a code."""
        user = self._own_with_factor(access)
        await self._auth.confirm(access, password)
        self._auth.confirm_code(access, code)
        self._remove(user, Actor.of(access))

    # --- another's ------------------------------------------------------------

    def remove(self, access: Access, user_id: str) -> None:
        """Another user's factor off, within the caller's rights. Its
        sessions end."""
        if user_id == access.user_id:
            raise ConflictError("remove your own second factor with a code")
        user = self._rules.managed(access, "remove_second_factor", user_id)
        if not self._factors.has(user_id):
            raise NotFoundError(f"{user.name} has no second factor")
        self._remove(user, Actor.of(access))

    def reset(self, name: str) -> User:
        """The factor of the user of this name off. For the command line
        on the host only, when its owner lost the app and the recovery
        codes: it checks no caller."""
        user = self._auth.user_named(name)
        if user is None:
            raise NotFoundError(f"no user is named {name}")
        if not self._factors.has(user.id):
            raise NotFoundError(f"{user.name} has no second factor")
        self._remove(user, HOST)
        return user

    def _remove(self, user: User, by: Actor) -> None:
        with self._activity.atomic():
            self._factors.remove(user.id)
            self._activity.record(said.SecondFactorRemoved(by=by, user=user))

    def _own_without_factor(self, access: Access) -> User:
        user = self._users.get(access.user_id)
        if self._factors.has(user.id):
            raise ConflictError("you have a second factor: remove it first")
        return user

    def _own_with_factor(self, access: Access) -> User:
        user = self._users.get(access.user_id)
        if not self._factors.has(user.id):
            raise ConflictError("you have no second factor")
        return user

    def _stamp(self, user_id: str) -> datetime:
        stamp = self._factors.stamp(user_id)
        if stamp is None:
            raise NotFoundError("the second factor is gone")
        return stamp
