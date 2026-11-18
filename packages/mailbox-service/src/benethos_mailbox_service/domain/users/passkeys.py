"""Passkeys of users who sign in to the UI: one's own added, renamed and
removed with the password and a code or a passkey, another's removed
within the caller's rights (docs/AUTHENTICATION.md 5).

Adding a passkey is for the person whose device makes it. Nobody adds
one for another user.
"""

from __future__ import annotations

from dataclasses import dataclass

from ...data.models import User
from ...data.secrets import Begun, Party
from ...data.storage import UserRepository
from ...errors import BadRequestError, ConflictError, NotFoundError
from ..activity import ActivityLog, Actor
from ..activity import users as said
from ..auth import Answer, AuthService, SecondFactors
from ..rights import Access
from .factors import DeviceAdded
from .rules import UserRules


@dataclass(frozen=True, slots=True)
class PasskeySetup:
    """A passkey begun: its name as it is kept, the options for the
    browser and the challenge for the server to keep. Nothing is stored
    yet."""

    name: str
    begun: Begun


class PasskeyService:
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
        self._passkeys = factors.passkeys
        self._rules = rules
        self._activity = activity

    # --- one's own ------------------------------------------------------------

    async def begin(
        self,
        access: Access,
        name: str,
        password: str,
        party: Party,
        code: str = "",
        answer: Answer | None = None,
    ) -> PasskeySetup:
        """The options to create a passkey called ``name`` for the caller,
        after its password once more, and with a second factor on already,
        a code or a passkey. Nothing is stored before ``confirm``."""
        user = self._users.get(access.user_id)
        name = self._passkeys.checked_name(user.id, name)
        await self._auth.confirm(access, password)
        if self._factors.has(user.id):
            self._auth.confirm_code(access, code, answer)
        return PasskeySetup(name, self._passkeys.registration(user, party))

    def confirm(self, access: Access, name: str, answer: Answer) -> DeviceAdded:
        """The passkey the browser created stored. Returns the recovery
        codes the first device of the second factor brings, to be shown
        once, and the new stamp, which keeps the caller's session and ends
        its others."""
        user = self._users.get(access.user_id)
        name = self._passkeys.checked_name(user.id, name)
        first = not self._factors.has(user.id)
        with self._activity.atomic():
            self._passkeys.add(user.id, name, answer)
            codes = self._factors.added(user.id, first)
            self._activity.record(
                said.PasskeyAdded(by=Actor.of(access), passkey=name, first=first)
            )
        stamp = self._factors.stamp(user.id)
        if stamp is None:
            raise NotFoundError("the second factor is gone")
        return DeviceAdded(codes, stamp)

    def rename(self, access: Access, passkey_id: str, name: str) -> None:
        before = self._own(access, passkey_id)
        name = self._passkeys.checked_name(access.user_id, name, passkey_id)
        if name == before:
            return
        with self._activity.atomic():
            self._passkeys.rename(access.user_id, passkey_id, name)
            self._activity.record(
                said.PasskeyRenamed(by=Actor.of(access), before=before, after=name)
            )

    async def remove_own(
        self,
        access: Access,
        passkey_ids: list[str],
        password: str,
        code: str = "",
        answer: Answer | None = None,
    ) -> str | None:
        """Some of the caller's passkeys after one password and one code or
        passkey, which may be one of them. None is removed when one is not
        the caller's. Returns the new stamp, which keeps the caller's
        session: None once the second factor is off."""
        if not passkey_ids:
            raise BadRequestError("tick at least one passkey")
        for passkey_id in passkey_ids:
            self._own(access, passkey_id)
        await self._auth.confirm(access, password)
        self._auth.confirm_code(access, code, answer)
        user = self._users.get(access.user_id)
        for passkey_id in dict.fromkeys(passkey_ids):
            self._remove(user, passkey_id, Actor.of(access))
        return self._factors.stamp(user.id)

    # --- another's ------------------------------------------------------------

    def remove_passkey(self, access: Access, user_id: str, passkey_id: str) -> None:
        """One passkey of another user, within the caller's rights. Its
        sessions end."""
        if user_id == access.user_id:
            raise ConflictError("remove your own passkeys with a code or a passkey")
        user = self._rules.managed(access, "remove_passkey", user_id)
        self._remove(user, passkey_id, Actor.of(access))

    def _remove(self, user: User, passkey_id: str, by: Actor) -> None:
        passkey = self._passkeys.passkey(user.id, passkey_id)
        if passkey is None:
            raise NotFoundError(f"{user.name} has no passkey {passkey_id}")
        with self._activity.atomic():
            self._passkeys.remove(user.id, passkey_id)
            last = self._factors.removed(user.id)
            self._activity.record(
                said.PasskeyRemoved(by=by, user=user, passkey=passkey.name, last=last)
            )

    def _own(self, access: Access, passkey_id: str) -> str:
        """The name of one of the caller's passkeys."""
        passkey = self._passkeys.passkey(access.user_id, passkey_id)
        if passkey is None:
            raise NotFoundError(f"you have no passkey {passkey_id}")
        return passkey.name
