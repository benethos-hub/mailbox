"""Second factors of users: the devices, each with its TOTP secret sealed,
and the hashes of the user's recovery codes (docs/AUTHENTICATION.md 6).

It only stores. The domain makes the secrets and the codes, and decides
who may add or remove a device.
"""

from __future__ import annotations

from dataclasses import dataclass, replace
from datetime import datetime
from typing import Protocol

from ...errors import NotFoundError
from .webhooks import Sealed


@dataclass(frozen=True)
class StoredDevice:
    """A device of a user's second factor. ``last_step`` is the step of
    the last code taken from it, none before the first."""

    id: str
    name: str
    secret: Sealed
    created_at: datetime
    last_step: int | None = None
    last_used_at: datetime | None = None


class SecondFactorRepository(Protocol):
    def devices(self, user_id: str) -> list[StoredDevice]:
        """The user's devices, oldest first."""
        ...

    def add(self, user_id: str, device: StoredDevice) -> None: ...

    def rename(self, user_id: str, device_id: str, name: str) -> None:
        """``NotFoundError`` for a device the user does not have."""
        ...

    def took(self, user_id: str, device_id: str, step: int, at: datetime) -> bool:
        """Note a code of ``step`` of the device as taken at ``at``. False
        when a code of that step or a later one was taken already: two
        requests with the same code cannot both pass."""
        ...

    def remove(self, user_id: str, device_id: str) -> bool:
        """One device. False when the user has none such."""
        ...

    def replace_codes(self, user_id: str, codes: list[str]) -> None: ...

    def use_code(self, user_id: str, code: str, at: datetime) -> bool:
        """Mark the recovery code with this hash used. False when the user
        has none such left."""
        ...

    def codes_left(self, user_id: str) -> int: ...

    def delete(self, user_id: str) -> bool:
        """Every device and the codes. False when the user had no device."""
        ...


class InMemorySecondFactorRepository:
    def __init__(self) -> None:
        self._devices: dict[str, dict[str, StoredDevice]] = {}
        # Per user: hash to when it was used, None while it is left.
        self._codes: dict[str, dict[str, datetime | None]] = {}

    def devices(self, user_id: str) -> list[StoredDevice]:
        held = self._devices.get(user_id, {}).values()
        return sorted(held, key=lambda d: (d.created_at, d.id))

    def add(self, user_id: str, device: StoredDevice) -> None:
        self._devices.setdefault(user_id, {})[device.id] = device

    def rename(self, user_id: str, device_id: str, name: str) -> None:
        device = self._held(user_id, device_id)
        self._devices[user_id][device_id] = replace(device, name=name)

    def took(self, user_id: str, device_id: str, step: int, at: datetime) -> bool:
        device = self._devices.get(user_id, {}).get(device_id)
        if device is None:
            return False
        if device.last_step is not None and device.last_step >= step:
            return False
        self._devices[user_id][device_id] = replace(
            device, last_step=step, last_used_at=at
        )
        return True

    def remove(self, user_id: str, device_id: str) -> bool:
        return self._devices.get(user_id, {}).pop(device_id, None) is not None

    def replace_codes(self, user_id: str, codes: list[str]) -> None:
        self._codes[user_id] = dict.fromkeys(codes)

    def use_code(self, user_id: str, code: str, at: datetime) -> bool:
        codes = self._codes.get(user_id, {})
        if code not in codes or codes[code] is not None:
            return False
        codes[code] = at
        return True

    def codes_left(self, user_id: str) -> int:
        return sum(1 for used in self._codes.get(user_id, {}).values() if used is None)

    def delete(self, user_id: str) -> bool:
        self._codes.pop(user_id, None)
        return bool(self._devices.pop(user_id, None))

    def _held(self, user_id: str, device_id: str) -> StoredDevice:
        device = self._devices.get(user_id, {}).get(device_id)
        if device is None:
            raise NotFoundError(f"no device {device_id}")
        return device
