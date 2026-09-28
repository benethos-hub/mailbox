"""Encrypted credentials and the wrapped data key. Only ciphertext passes here."""

from __future__ import annotations

from dataclasses import dataclass
from datetime import datetime
from typing import Protocol

from .table import Table, drop_where


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
        self._keys: Table[WrappedKey] = Table("key")

    def active(self) -> WrappedKey | None:
        keys = self._keys.list()
        return keys[-1] if keys else None

    def add(self, key: WrappedKey) -> None:
        self._keys.add(key.key_id, key)


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
        drop_where(self._items, lambda key, _: key[0] == account_id)
