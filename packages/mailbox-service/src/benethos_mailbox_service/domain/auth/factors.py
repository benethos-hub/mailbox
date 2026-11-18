"""The second factor of a user: the frame its methods share
(docs/AUTHENTICATION.md 2).

The frame knows which methods a user has, checks a code against each of
them and then the recovery codes, makes the recovery codes with the
first method and drops them with the last. TOTP, in ``totp``, is the
first method, passkeys, in ``passkeys``, the second.
"""

from __future__ import annotations

from dataclasses import dataclass
from datetime import timedelta
from typing import Literal

from benethos_mailbox_common.values import secret

from ...data.models import SecondFactor
from ...data.secrets import Begun, Party
from .passkeys import Answer, Passkeys
from .recovery import RecoveryCodes
from .totp import Totp

# How a code at the sign-in was taken: a method's, or a recovery code.
Kind = Literal["totp", "passkey", "recovery"]

# A pending sign-in, between the password and the code, ends after this,
# or after this many wrong codes.
PENDING = timedelta(minutes=5)
CODE_TRIES = 5


@dataclass(frozen=True)
class Taken:
    """A code or a passkey that passed: of which kind, and the device of
    a method."""

    kind: Kind
    device: str | None = None


class SecondFactors:
    """The frame of every user's second factor, over its methods."""

    def __init__(self, totp: Totp, passkeys: Passkeys, recovery: RecoveryCodes) -> None:
        self.totp = totp
        self.passkeys = passkeys
        self.recovery = recovery

    def has(self, user_id: str) -> bool:
        """On while any method has a device."""
        return bool(self.totp.ids(user_id) or self.passkeys.ids(user_id))

    def stamp(self, user_id: str) -> str | None:
        """Which devices of which methods the user has, as one value. A
        session keeps it and ends once a device is added or removed. None
        without a second factor."""
        held = sorted(
            [f"totp:{i}" for i in self.totp.ids(user_id)]
            + [f"passkey:{i}" for i in self.passkeys.ids(user_id)]
        )
        return secret.digest(",".join(held)) if held else None

    def state(self, user_id: str) -> SecondFactor:
        return SecondFactor(
            totp=self.totp.devices(user_id),
            passkeys=self.passkeys.passkeys(user_id),
            recovery_codes_left=self.recovery.left(user_id),
        )

    def challenge(self, user_id: str, party: Party) -> Begun | None:
        """The options to sign with one of the user's passkeys, the
        challenge for the server to keep. None for a user without one."""
        return self.passkeys.challenge(user_id, party)

    def codes_left(self, user_id: str) -> int:
        return self.recovery.left(user_id)

    def check(
        self, user_id: str, presented: str, answer: Answer | None = None
    ) -> Taken | None:
        """Whether ``presented`` is a code of one of the user's methods not
        taken before, or one of its recovery codes left, or ``answer`` a
        signature of one of its passkeys. Either is used up."""
        if not self.has(user_id):
            return None
        if answer is not None:
            passkey = self.passkeys.check(user_id, answer)
            return Taken("passkey", passkey) if passkey is not None else None
        if presented.strip().isdigit():
            device = self.totp.check(user_id, presented)
            if device is not None:
                return Taken("totp", device)
        # A recovery code may be digits alone as well.
        return Taken("recovery") if self.recovery.use(user_id, presented) else None

    def added(self, user_id: str, first: bool) -> list[str]:
        """A method's device was added. The first turns the factor on and
        brings the recovery codes, to be shown once. Else none."""
        return self.recovery.make(user_id) if first else []

    def removed(self, user_id: str) -> bool:
        """A method's device was removed. With the last one the factor is
        off and the recovery codes go: then True."""
        if self.has(user_id):
            return False
        self.recovery.delete(user_id)
        return True

    def renew_codes(self, user_id: str) -> list[str]:
        """A new set of recovery codes in place of the old."""
        return self.recovery.make(user_id)

    def remove(self, user_id: str) -> bool:
        """Every method and the recovery codes. False when the user had
        none."""
        had = self.totp.remove_all(user_id)
        had = self.passkeys.remove_all(user_id) or had
        self.recovery.delete(user_id)
        return had
