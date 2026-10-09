"""The second factor of a user: its devices, each with a TOTP secret of
its own, and one set of recovery codes (docs/AUTHENTICATION.md).

This module checks a code and keeps what goes with a factor. Who may
add or remove a device is decided in ``domain/users/factors.py``, the
sign-in with it in ``AuthService``.
"""

from __future__ import annotations

import secrets
from collections.abc import Callable
from dataclasses import dataclass
from datetime import datetime, timedelta
from typing import Literal

from pydantic import SecretStr

from ...common.clock import utc_now
from ...common.secret import digest, new_id
from ...data.models import FactorDevice, SecondFactor
from ...data.secrets import CredentialVault, totp
from ...data.storage import SecondFactorRepository, StoredDevice
from ...errors import BadRequestError, ConflictError

# How a code at the sign-in was taken.
Kind = Literal["totp", "recovery"]

# A pending sign-in, between the password and the code, ends after this,
# or after this many wrong codes.
PENDING = timedelta(minutes=5)
CODE_TRIES = 5
# A secret shown for setup and not yet confirmed is dropped after this.
SETUP = timedelta(minutes=15)
# Devices of one user, and the length of a device's name.
MAX_DEVICES = 10
MAX_DEVICE_NAME = 60

RECOVERY_CODES = 10
# Crockford's base32: no I, L, O or U, so nothing is mistaken for 1 or 0.
_ALPHABET = "0123456789ABCDEFGHJKMNPQRSTVWXYZ"
_GROUP = 5
_LENGTH = 2 * _GROUP
# What a person may type for a character of the alphabet.
_READ_AS = str.maketrans({"I": "1", "L": "1", "O": "0"})


@dataclass(frozen=True)
class Taken:
    """A code that passed: of which kind, and the device of a code of the
    app."""

    kind: Kind
    device: str | None = None


def new_recovery_code() -> str:
    """Ten characters of 32, 50 bits, shown as two groups of five."""
    text = "".join(secrets.choice(_ALPHABET) for _ in range(_LENGTH))
    return f"{text[:_GROUP]}-{text[_GROUP:]}"


def recovery_hash(presented: str) -> str | None:
    """The hash a recovery code is stored as. Case, spaces and dashes do
    not count. None for what cannot be one."""
    text = "".join(presented.split()).replace("-", "").upper().translate(_READ_AS)
    if len(text) != _LENGTH or any(c not in _ALPHABET for c in text):
        return None
    return digest(text)


class SecondFactors:
    """The factors of every user: devices added, checked, removed."""

    def __init__(
        self,
        repository: SecondFactorRepository,
        vault: CredentialVault,
        clock: Callable[[], datetime] = utc_now,
    ) -> None:
        self._repository = repository
        self._vault = vault
        self._clock = clock

    def has(self, user_id: str) -> bool:
        return bool(self._repository.devices(user_id))

    def stamp(self, user_id: str) -> str | None:
        """Which devices the user has, as one value. A session keeps it and
        ends once a device is added or removed. None without one."""
        ids = sorted(d.id for d in self._repository.devices(user_id))
        return digest(",".join(ids)) if ids else None

    def state(self, user_id: str) -> SecondFactor:
        return SecondFactor(
            devices=[_shown(d) for d in self._repository.devices(user_id)],
            recovery_codes_left=self._repository.codes_left(user_id),
        )

    def codes_left(self, user_id: str) -> int:
        return self._repository.codes_left(user_id)

    def device(self, user_id: str, device_id: str) -> FactorDevice | None:
        found = [d for d in self._repository.devices(user_id) if d.id == device_id]
        return _shown(found[0]) if found else None

    def checked_name(
        self, user_id: str, name: str, device_id: str | None = None
    ) -> str:
        """``name`` as a device of the user may be called: not empty, not
        too long, no line breaks, not the name of another of its devices,
        whatever the case. A new device needs a free place too."""
        name = " ".join(name.split())
        if not name:
            raise BadRequestError("a device needs a name")
        if len(name) > MAX_DEVICE_NAME:
            raise BadRequestError(
                f"a device's name has at most {MAX_DEVICE_NAME} characters"
            )
        devices = self._repository.devices(user_id)
        wanted = name.casefold()
        if any(d.name.casefold() == wanted and d.id != device_id for d in devices):
            raise ConflictError(f"a device named {name} exists")
        if device_id is None and len(devices) >= MAX_DEVICES:
            raise ConflictError(f"at most {MAX_DEVICES} devices: remove one first")
        return name

    def check(self, user_id: str, presented: str) -> Taken | None:
        """Whether ``presented`` is a code of one of the user's devices not
        taken before, or one of its recovery codes left. Either is used
        up."""
        if presented.strip().isdigit():
            now = self._clock()
            for device in self._repository.devices(user_id):
                step = totp.matching_step(
                    self._unsealed(device), presented, now, after=device.last_step
                )
                if step is not None and self._repository.took(
                    user_id, device.id, step, now
                ):
                    return Taken("totp", device.name)
            return None
        hashed = recovery_hash(presented)
        if hashed is not None and self._repository.use_code(
            user_id, hashed, self._clock()
        ):
            return Taken("recovery")
        return None

    def add(
        self, user_id: str, name: str, secret: bytes, presented: str
    ) -> list[str] | None:
        """Store ``secret`` as a new device once ``presented`` is its code
        now. Returns the recovery codes the first device brings, to be
        shown once, an empty list for a further one. None when the code
        is not right."""
        now = self._clock()
        step = totp.matching_step(secret, presented, now)
        if step is None:
            return None
        device_id = new_id("tfa")
        sealed = self._vault.seal(_label(device_id), SecretStr(totp.base32(secret)))
        first = not self.has(user_id)
        self._repository.add(
            user_id,
            StoredDevice(device_id, name, sealed, now, last_step=step),
        )
        if not first:
            return []
        codes = [new_recovery_code() for _ in range(RECOVERY_CODES)]
        self._repository.replace_codes(user_id, [_hashed(code) for code in codes])
        return codes

    def rename(self, user_id: str, device_id: str, name: str) -> None:
        self._repository.rename(user_id, device_id, name)

    def remove_device(self, user_id: str, device_id: str) -> bool:
        """One device. With the last one the recovery codes go too. False
        when the user has none such."""
        if not self._repository.remove(user_id, device_id):
            return False
        if not self.has(user_id):
            self._repository.delete(user_id)
        return True

    def renew_codes(self, user_id: str) -> list[str]:
        """A new set of recovery codes in place of the old."""
        codes = [new_recovery_code() for _ in range(RECOVERY_CODES)]
        self._repository.replace_codes(user_id, [_hashed(code) for code in codes])
        return codes

    def remove(self, user_id: str) -> bool:
        """Every device and the codes. False when the user had none."""
        return self._repository.delete(user_id)

    def _unsealed(self, device: StoredDevice) -> bytes:
        written = self._vault.unseal(_label(device.id), device.secret)
        return totp.from_base32(written.get_secret_value())


def _label(device_id: str) -> str:
    """What a sealed secret is bound to: one device."""
    return f"totp:{device_id}"


def _shown(device: StoredDevice) -> FactorDevice:
    return FactorDevice(
        id=device.id,
        name=device.name,
        created_at=device.created_at,
        last_used_at=device.last_used_at,
    )


def _hashed(code: str) -> str:
    """The hash of a code made here, which is always one."""
    return digest(code.replace("-", ""))
