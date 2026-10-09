"""TOTP devices of users who sign in to the UI: one's own added, renamed
and removed with the password and a code, another's removed within the
caller's rights (docs/AUTHENTICATION.md 5).

Adding a device is for the person who scans the secret. Nobody adds one
for another user.
"""

from __future__ import annotations

from ...data.models import User
from ...data.secrets import totp
from ...data.storage import UserRepository
from ...errors import BadRequestError, ConflictError, NotFoundError
from ..activity import ActivityLog, Actor
from ..activity import users as said
from ..auth import AuthService, SecondFactors
from ..rights import Access
from .rules import UserRules


class TotpService:
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
        self._totp = factors.totp
        self._rules = rules
        self._activity = activity

    # --- one's own ------------------------------------------------------------

    async def begin(
        self, access: Access, name: str, password: str, code: str = ""
    ) -> tuple[str, bytes]:
        """A new secret for the caller to scan into a device called
        ``name``, after its password once more, and with a second factor
        on already, a code. Returns the name as it is kept and the secret.
        Nothing is stored before ``confirm``."""
        user = self._users.get(access.user_id)
        name = self._totp.checked_name(user.id, name)
        await self._auth.confirm(access, password)
        if self._factors.has(user.id):
            self._auth.confirm_code(access, code)
        return name, totp.new_secret()

    def confirm(
        self, access: Access, name: str, secret: bytes, code: str
    ) -> tuple[list[str], str]:
        """The device stored, once ``code`` is the secret's code now.
        Returns the recovery codes the first device of the second factor
        brings, to be shown once, and the new stamp, which keeps the
        caller's session and ends its others."""
        user = self._users.get(access.user_id)
        name = self._totp.checked_name(user.id, name)
        first = not self._factors.has(user.id)
        with self._activity.atomic():
            if not self._totp.add(user.id, name, secret, code):
                raise BadRequestError(
                    "the code is not right: check the time on the phone"
                )
            codes = self._factors.added(user.id, first)
            self._activity.record(
                said.TotpAdded(by=Actor.of(access), device=name, first=first)
            )
        stamp = self._factors.stamp(user.id)
        if stamp is None:
            raise NotFoundError("the second factor is gone")
        return codes, stamp

    def rename(self, access: Access, device_id: str, name: str) -> None:
        before = self._own_device(access, device_id)
        name = self._totp.checked_name(access.user_id, name, device_id)
        if name == before:
            return
        with self._activity.atomic():
            self._totp.rename(access.user_id, device_id, name)
            self._activity.record(
                said.TotpRenamed(by=Actor.of(access), before=before, after=name)
            )

    async def remove_own(
        self, access: Access, device_id: str, password: str, code: str
    ) -> str | None:
        """One of the caller's devices, with its password and a code.
        Returns the new stamp, which keeps the caller's session: None once
        the second factor is off."""
        self._own_device(access, device_id)
        await self._auth.confirm(access, password)
        self._auth.confirm_code(access, code)
        user = self._users.get(access.user_id)
        self._remove(user, device_id, Actor.of(access))
        return self._factors.stamp(user.id)

    # --- another's ------------------------------------------------------------

    def remove_device(self, access: Access, user_id: str, device_id: str) -> None:
        """One device of another user, within the caller's rights. Its
        sessions end."""
        if user_id == access.user_id:
            raise ConflictError("remove your own devices with a code")
        user = self._rules.managed(access, "remove_totp_device", user_id)
        self._remove(user, device_id, Actor.of(access))

    def _remove(self, user: User, device_id: str, by: Actor) -> None:
        device = self._totp.device(user.id, device_id)
        if device is None:
            raise NotFoundError(f"{user.name} has no device {device_id}")
        with self._activity.atomic():
            self._totp.remove(user.id, device_id)
            last = self._factors.removed(user.id)
            self._activity.record(
                said.TotpRemoved(by=by, user=user, device=device.name, last=last)
            )

    def _own_device(self, access: Access, device_id: str) -> str:
        """The name of one of the caller's devices."""
        device = self._totp.device(access.user_id, device_id)
        if device is None:
            raise NotFoundError(f"you have no device {device_id}")
        return device.name
