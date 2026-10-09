"""The TOTP devices of users, each with its secret sealed
(docs/AUTHENTICATION.md 3, 7). TOTP is one method of the second factor.

It only stores. The domain makes the secrets, and decides who may add
or remove a device.
"""

from __future__ import annotations

from dataclasses import dataclass, replace
from datetime import datetime
from typing import Protocol

from ...errors import NotFoundError
from .webhooks import Sealed


@dataclass(frozen=True)
class StoredTotpDevice:
    """A TOTP device of a user. ``last_step`` is the step of the last code
    taken from it, none before the first."""

    id: str
    name: str
    secret: Sealed
    created_at: datetime
    last_step: int | None = None
    last_used_at: datetime | None = None


class TotpRepository(Protocol):
    def devices(self, user_id: str) -> list[StoredTotpDevice]:
        """The user's devices, oldest first."""
        ...

    def add(self, user_id: str, device: StoredTotpDevice) -> None: ...

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

    def remove_all(self, user_id: str) -> bool:
        """Every device of the user. False when it had none."""
        ...


class InMemoryTotpRepository:
    def __init__(self) -> None:
        self._devices: dict[str, dict[str, StoredTotpDevice]] = {}

    def devices(self, user_id: str) -> list[StoredTotpDevice]:
        held = self._devices.get(user_id, {}).values()
        return sorted(held, key=lambda d: (d.created_at, d.id))

    def add(self, user_id: str, device: StoredTotpDevice) -> None:
        self._devices.setdefault(user_id, {})[device.id] = device

    def rename(self, user_id: str, device_id: str, name: str) -> None:
        device = self._devices.get(user_id, {}).get(device_id)
        if device is None:
            raise NotFoundError(f"no device {device_id}")
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

    def remove_all(self, user_id: str) -> bool:
        return bool(self._devices.pop(user_id, None))
