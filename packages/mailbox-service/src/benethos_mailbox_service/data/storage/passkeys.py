"""The passkeys of users (docs/AUTHENTICATION.md 5, 7). Passkeys are one
method of the second factor.

It only stores. A passkey holds a public key, no secret: whoever reads it
cannot sign in with it. The domain checks the signatures, and decides who
may add or remove a passkey.
"""

from __future__ import annotations

from dataclasses import dataclass, replace
from datetime import datetime
from typing import Protocol

from ...errors import ConflictError, NotFoundError


@dataclass(frozen=True, slots=True)
class StoredPasskey:
    """A passkey of a user: its credential id, the attested credential
    data with the public key, and the counter of its last signature, zero
    for a passkey that keeps none."""

    id: str
    name: str
    credential_id: bytes
    credential: bytes
    created_at: datetime
    sign_count: int = 0
    last_used_at: datetime | None = None


class PasskeyRepository(Protocol):
    def passkeys(self, user_id: str) -> list[StoredPasskey]:
        """The user's passkeys, oldest first."""
        ...

    def add(self, user_id: str, passkey: StoredPasskey) -> None:
        """``ConflictError`` for a credential id stored already, the
        user's or another's."""
        ...

    def rename(self, user_id: str, passkey_id: str, name: str) -> None:
        """``NotFoundError`` for a passkey the user does not have."""
        ...

    def used(
        self, user_id: str, passkey_id: str, sign_count: int, at: datetime
    ) -> bool:
        """Note a signature with ``sign_count`` as taken at ``at``. False
        when the counter did not grow, as a copy of the key would show:
        two requests with the same signature cannot both pass. A passkey
        whose counter stays at zero keeps none."""
        ...

    def remove(self, user_id: str, passkey_id: str) -> bool:
        """One passkey. False when the user has none such."""
        ...

    def remove_all(self, user_id: str) -> bool:
        """Every passkey of the user. False when it had none."""
        ...


def counted(stored: int, presented: int) -> bool:
    """Whether a signature's counter may follow the stored one: higher, or
    both zero for a passkey that keeps no counter."""
    return presented > stored or presented == stored == 0


class InMemoryPasskeyRepository:
    def __init__(self) -> None:
        self._passkeys: dict[str, dict[str, StoredPasskey]] = {}

    def passkeys(self, user_id: str) -> list[StoredPasskey]:
        held = self._passkeys.get(user_id, {}).values()
        return sorted(held, key=lambda p: (p.created_at, p.id))

    def add(self, user_id: str, passkey: StoredPasskey) -> None:
        if any(
            p.credential_id == passkey.credential_id
            for held in self._passkeys.values()
            for p in held.values()
        ):
            raise ConflictError("this passkey is stored already")
        self._passkeys.setdefault(user_id, {})[passkey.id] = passkey

    def rename(self, user_id: str, passkey_id: str, name: str) -> None:
        passkey = self._passkeys.get(user_id, {}).get(passkey_id)
        if passkey is None:
            raise NotFoundError(f"no passkey {passkey_id}")
        self._passkeys[user_id][passkey_id] = replace(passkey, name=name)

    def used(
        self, user_id: str, passkey_id: str, sign_count: int, at: datetime
    ) -> bool:
        passkey = self._passkeys.get(user_id, {}).get(passkey_id)
        if passkey is None or not counted(passkey.sign_count, sign_count):
            return False
        self._passkeys[user_id][passkey_id] = replace(
            passkey, sign_count=sign_count, last_used_at=at
        )
        return True

    def remove(self, user_id: str, passkey_id: str) -> bool:
        return self._passkeys.get(user_id, {}).pop(passkey_id, None) is not None

    def remove_all(self, user_id: str) -> bool:
        return bool(self._passkeys.pop(user_id, None))
