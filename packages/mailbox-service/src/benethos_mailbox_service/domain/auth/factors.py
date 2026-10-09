"""The second factor of a user: the frame its methods share
(docs/AUTHENTICATION.md 2).

The frame knows which methods a user has, checks a code against each of
them and then the recovery codes, makes the recovery codes with the
first method and drops them with the last. TOTP, in ``totp``, is the
first method. A later one, such as passkeys, joins here beside it.
"""

from __future__ import annotations

from dataclasses import dataclass
from datetime import timedelta
from typing import Literal

from ...common.secret import digest
from ...data.models import SecondFactor
from .recovery import RecoveryCodes
from .totp import Totp

# How a code at the sign-in was taken: a method's, or a recovery code.
Kind = Literal["totp", "recovery"]

# A pending sign-in, between the password and the code, ends after this,
# or after this many wrong codes.
PENDING = timedelta(minutes=5)
CODE_TRIES = 5


@dataclass(frozen=True)
class Taken:
    """A code that passed: of which kind, and the device of a method's
    code."""

    kind: Kind
    device: str | None = None


class SecondFactors:
    """The frame of every user's second factor, over its methods."""

    def __init__(self, totp: Totp, recovery: RecoveryCodes) -> None:
        self.totp = totp
        self.recovery = recovery

    def has(self, user_id: str) -> bool:
        """On while any method has a device."""
        return bool(self.totp.ids(user_id))

    def stamp(self, user_id: str) -> str | None:
        """Which devices of which methods the user has, as one value. A
        session keeps it and ends once a device is added or removed. None
        without a second factor."""
        held = sorted(f"totp:{i}" for i in self.totp.ids(user_id))
        return digest(",".join(held)) if held else None

    def state(self, user_id: str) -> SecondFactor:
        return SecondFactor(
            totp=self.totp.devices(user_id),
            recovery_codes_left=self.recovery.left(user_id),
        )

    def codes_left(self, user_id: str) -> int:
        return self.recovery.left(user_id)

    def check(self, user_id: str, presented: str) -> Taken | None:
        """Whether ``presented`` is a code of one of the user's methods not
        taken before, or one of its recovery codes left. Either is used
        up."""
        if not self.has(user_id):
            return None
        if presented.strip().isdigit():
            device = self.totp.check(user_id, presented)
            return Taken("totp", device) if device is not None else None
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
        self.recovery.delete(user_id)
        return had
