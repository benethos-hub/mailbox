"""TOTP, the first method of the second factor: a user's authenticator
apps, each a device with a secret of its own (docs/AUTHENTICATION.md 3,
5).

This module checks a code and keeps the devices. The frame they belong
to is ``factors``, who may add or remove one ``domain/users/totp.py``.
"""

from __future__ import annotations

from collections.abc import Callable
from datetime import datetime, timedelta

from pydantic import SecretStr

# Named apart from a secret of its own.
from benethos_mailbox_common.values import secret as secret_values

from ...common.clock import utc_now
from ...data.models import TotpDevice
from ...data.secrets import CredentialVault, totp
from ...data.storage import StoredTotpDevice, TotpRepository
from ...errors import BadRequestError, ConflictError

# A secret shown for a new device and not yet confirmed is dropped after
# this.
SETUP = timedelta(minutes=15)
# Devices of one user, and the length of a device's name.
MAX_DEVICES = 10
MAX_DEVICE_NAME = 60


class Totp:
    """The TOTP devices of every user: added, checked, removed."""

    def __init__(
        self,
        repository: TotpRepository,
        vault: CredentialVault,
        clock: Callable[[], datetime] = utc_now,
    ) -> None:
        self._repository = repository
        self._vault = vault
        self._clock = clock

    def devices(self, user_id: str) -> list[TotpDevice]:
        """Oldest first, never a secret."""
        return [_shown(d) for d in self._repository.devices(user_id)]

    def ids(self, user_id: str) -> list[str]:
        return [d.id for d in self._repository.devices(user_id)]

    def device(self, user_id: str, device_id: str) -> TotpDevice | None:
        found = [d for d in self.devices(user_id) if d.id == device_id]
        return found[0] if found else None

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

    def check(self, user_id: str, presented: str) -> str | None:
        """The name of the device whose code ``presented`` is, not taken
        before. It is used up. None for none."""
        now = self._clock()
        for device in self._repository.devices(user_id):
            step = totp.matching_step(
                self._unsealed(device), presented, now, after=device.last_step
            )
            if step is not None and self._repository.took(
                user_id, device.id, step, now
            ):
                return device.name
        return None

    def add(self, user_id: str, name: str, secret: bytes, presented: str) -> bool:
        """Store ``secret`` as a new device once ``presented`` is its code
        now. False when the code is not right."""
        now = self._clock()
        step = totp.matching_step(secret, presented, now)
        if step is None:
            return False
        device_id = secret_values.new_id("tfa")
        sealed = self._vault.seal(_label(device_id), SecretStr(totp.base32(secret)))
        self._repository.add(
            user_id, StoredTotpDevice(device_id, name, sealed, now, last_step=step)
        )
        return True

    def rename(self, user_id: str, device_id: str, name: str) -> None:
        self._repository.rename(user_id, device_id, name)

    def remove(self, user_id: str, device_id: str) -> bool:
        return self._repository.remove(user_id, device_id)

    def remove_all(self, user_id: str) -> bool:
        return self._repository.remove_all(user_id)

    def _unsealed(self, device: StoredTotpDevice) -> bytes:
        written = self._vault.unseal(_label(device.id), device.secret)
        return totp.from_base32(written.get_secret_value())


def _label(device_id: str) -> str:
    """What a sealed secret is bound to: one device."""
    return f"totp:{device_id}"


def _shown(device: StoredTotpDevice) -> TotpDevice:
    return TotpDevice(
        id=device.id,
        name=device.name,
        created_at=device.created_at,
        last_used_at=device.last_used_at,
    )
