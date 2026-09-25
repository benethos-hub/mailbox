"""Encrypted credentials and the wrapped data key. Only ciphertext passes here."""

from __future__ import annotations

from dataclasses import dataclass
from datetime import datetime
from typing import Protocol

from ...errors import ConflictError


@dataclass(frozen=True)
class WrappedKey:
    key_id: str
    nonce: bytes
    ciphertext: bytes


@dataclass(frozen=True)
class EncryptedCredential:
    account_id: str
    field: str
    key_id: str
    nonce: bytes
    ciphertext: bytes
    updated_at: datetime


class KeyRepository(Protocol):
    def active(self) -> WrappedKey | None: ...

    def add(self, key: WrappedKey) -> None: ...


class CredentialRepository(Protocol):
    def put(self, credential: EncryptedCredential) -> None: ...

    def get(self, account_id: str, field: str) -> EncryptedCredential | None: ...

    def list_for_account(self, account_id: str) -> list[EncryptedCredential]: ...

    def delete_for_account(self, account_id: str) -> None: ...


class InMemoryKeyRepository:
    def __init__(self) -> None:
        self._keys: list[WrappedKey] = []

    def active(self) -> WrappedKey | None:
        return self._keys[-1] if self._keys else None

    def add(self, key: WrappedKey) -> None:
        if any(k.key_id == key.key_id for k in self._keys):
            raise ConflictError(f"key {key.key_id} exists already")
        self._keys.append(key)


class InMemoryCredentialRepository:
    def __init__(self) -> None:
        self._items: dict[tuple[str, str], EncryptedCredential] = {}

    def put(self, credential: EncryptedCredential) -> None:
        self._items[(credential.account_id, credential.field)] = credential

    def get(self, account_id: str, field: str) -> EncryptedCredential | None:
        return self._items.get((account_id, field))

    def list_for_account(self, account_id: str) -> list[EncryptedCredential]:
        return [c for (a, _), c in sorted(self._items.items()) if a == account_id]

    def delete_for_account(self, account_id: str) -> None:
        for key in [k for k in self._items if k[0] == account_id]:
            del self._items[key]
