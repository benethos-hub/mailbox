"""The second factor of users who sign in to the UI: one's own devices
added, renamed and removed with the password and a code, another's
removed within the caller's rights, every one removed on the host
(docs/AUTHENTICATION.md 4).

Adding a device is for the person who scans the secret. Nobody adds one
for another user.
"""

from __future__ import annotations

from ...data.models import SecondFactor, User
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

    def mine(self, access: Access) -> SecondFactor:
        """The caller's own devices and recovery codes left."""
        return self._factors.state(access.user_id)

    # --- one's own ------------------------------------------------------------

    async def begin(
        self, access: Access, name: str, password: str, code: str = ""
    ) -> tuple[str, bytes]:
        """A new secret for the caller to scan into a device called
        ``name``, after its password once more, and with a device there
        already, a code. Returns the name as it is kept and the secret.
        Nothing is stored before ``confirm``."""
        user = self._users.get(access.user_id)
        name = self._factors.checked_name(user.id, name)
        await self._auth.confirm(access, password)
        if self._factors.has(user.id):
            self._auth.confirm_code(access, code)
        return name, totp.new_secret()

    def confirm(
        self, access: Access, name: str, secret: bytes, code: str
    ) -> tuple[list[str], str]:
        """The device stored, once ``code`` is the secret's code now.
        Returns the recovery codes the first device brings, to be shown
        once, and the new stamp, which keeps the caller's session and
        ends its others."""
        user = self._users.get(access.user_id)
        name = self._factors.checked_name(user.id, name)
        first = not self._factors.has(user.id)
        with self._activity.atomic():
            codes = self._factors.add(user.id, name, secret, code)
            if codes is None:
                raise BadRequestError(
                    "the code is not right: check the time on the phone"
                )
            self._activity.record(
                said.DeviceAdded(by=Actor.of(access), device=name, first=first)
            )
        return codes, self._stamp(user.id)

    def rename(self, access: Access, device_id: str, name: str) -> None:
        before = self._own_device(access, device_id)
        name = self._factors.checked_name(access.user_id, name, device_id)
        if name == before:
            return
        with self._activity.atomic():
            self._factors.rename(access.user_id, device_id, name)
            self._activity.record(
                said.DeviceRenamed(by=Actor.of(access), before=before, after=name)
            )

    async def renew_codes(self, access: Access, password: str) -> list[str]:
        """A new set of recovery codes for the caller, in place of the old,
        after its password once more."""
        user = self._users.get(access.user_id)
        if not self._factors.has(user.id):
            raise ConflictError("you have no second factor")
        await self._auth.confirm(access, password)
        with self._activity.atomic():
            codes = self._factors.renew_codes(user.id)
            self._activity.record(said.RecoveryCodesRenewed(by=Actor.of(access)))
        return codes

    async def remove_own(
        self, access: Access, device_id: str, password: str, code: str
    ) -> str | None:
        """One of the caller's devices, with its password and a code.
        Returns the new stamp, which keeps the caller's session: None once
        the last device is gone."""
        self._own_device(access, device_id)
        await self._auth.confirm(access, password)
        self._auth.confirm_code(access, code)
        user = self._users.get(access.user_id)
        self._remove_device(user, device_id, Actor.of(access))
        return self._factors.stamp(user.id)

    # --- another's ------------------------------------------------------------

    def of(self, access: Access, user_id: str) -> SecondFactor:
        """Another user's devices, never a secret."""
        access.require("get_second_factor")
        self._users.get(user_id)
        return self._factors.state(user_id)

    def remove(self, access: Access, user_id: str) -> None:
        """Every device of another user, within the caller's rights. Its
        sessions end."""
        user = self._managed(access, "remove_second_factor", user_id)
        if not self._factors.has(user_id):
            raise NotFoundError(f"{user.name} has no second factor")
        self._remove_all(user, Actor.of(access))

    def remove_device(self, access: Access, user_id: str, device_id: str) -> None:
        """One device of another user, within the caller's rights. Its
        sessions end."""
        user = self._managed(access, "remove_factor_device", user_id)
        self._remove_device(user, device_id, Actor.of(access))

    def reset(self, name: str) -> User:
        """Every device of the user of this name. For the command line on
        the host only, when its owner lost them and the recovery codes: it
        checks no caller."""
        user = self._auth.user_named(name)
        if user is None:
            raise NotFoundError(f"no user is named {name}")
        if not self._factors.has(user.id):
            raise NotFoundError(f"{user.name} has no second factor")
        self._remove_all(user, HOST)
        return user

    def _managed(self, access: Access, operation: str, user_id: str) -> User:
        if user_id == access.user_id:
            raise ConflictError("remove your own devices with a code")
        return self._rules.managed(access, operation, user_id)

    def _remove_device(self, user: User, device_id: str, by: Actor) -> None:
        device = self._factors.device(user.id, device_id)
        if device is None:
            raise NotFoundError(f"{user.name} has no device {device_id}")
        with self._activity.atomic():
            self._factors.remove_device(user.id, device_id)
            self._activity.record(
                said.DeviceRemoved(
                    by=by,
                    user=user,
                    device=device.name,
                    last=not self._factors.has(user.id),
                )
            )

    def _remove_all(self, user: User, by: Actor) -> None:
        with self._activity.atomic():
            self._factors.remove(user.id)
            self._activity.record(said.SecondFactorRemoved(by=by, user=user))

    def _own_device(self, access: Access, device_id: str) -> str:
        """The name of one of the caller's devices."""
        device = self._factors.device(access.user_id, device_id)
        if device is None:
            raise NotFoundError(f"you have no device {device_id}")
        return device.name

    def _stamp(self, user_id: str) -> str:
        stamp = self._factors.stamp(user_id)
        if stamp is None:
            raise NotFoundError("the second factor is gone")
        return stamp
