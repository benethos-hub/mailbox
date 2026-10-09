"""The second factor of users who sign in to the UI, as a whole: its
state, new recovery codes, and every method removed within the caller's
rights or on the host (docs/AUTHENTICATION.md 2, 5, 6). What each
method does is in a module of its own, TOTP in ``totp``.
"""

from __future__ import annotations

from ...data.models import SecondFactor, User
from ...data.storage import UserRepository
from ...errors import ConflictError, NotFoundError
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

    def mine(self, access: Access) -> SecondFactor:
        """The caller's own methods and recovery codes left."""
        return self._factors.state(access.user_id)

    def of(self, access: Access, user_id: str) -> SecondFactor:
        """Another user's methods, never a secret."""
        access.require("get_second_factor")
        self._users.get(user_id)
        return self._factors.state(user_id)

    async def renew_codes(self, access: Access, password: str, code: str) -> list[str]:
        """A new set of recovery codes for the caller, in place of the old,
        after its password once more and a code: of any of its devices,
        or one of the old recovery codes."""
        user = self._users.get(access.user_id)
        if not self._factors.has(user.id):
            raise ConflictError("you have no second factor")
        await self._auth.confirm(access, password)
        self._auth.confirm_code(access, code)
        with self._activity.atomic():
            codes = self._factors.renew_codes(user.id)
            self._activity.record(said.RecoveryCodesRenewed(by=Actor.of(access)))
        return codes

    def remove(self, access: Access, user_id: str) -> None:
        """Every method of another user and the recovery codes, within the
        caller's rights. Its sessions end."""
        if user_id == access.user_id:
            raise ConflictError("remove your own devices with a code")
        user = self._rules.managed(access, "remove_second_factor", user_id)
        if not self._factors.has(user_id):
            raise NotFoundError(f"{user.name} has no second factor")
        self._remove(user, Actor.of(access))

    def reset(self, name: str) -> User:
        """Every method of the user of this name and the recovery codes.
        For the command line on the host only, when its owner lost them
        all: it checks no caller."""
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
