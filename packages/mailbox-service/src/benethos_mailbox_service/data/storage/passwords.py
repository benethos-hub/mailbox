"""Password hashes of users (CONCEPT 7.5).

It only stores. The domain decides who may set one and what it must be.
"""

from __future__ import annotations

from dataclasses import dataclass, replace
from datetime import datetime
from typing import Protocol


@dataclass(frozen=True, slots=True)
class StoredPassword:
    hash: str
    # Set by someone else, or made by create-admin: change it at sign-in.
    must_change: bool
    updated_at: datetime
    # The last sign-in to the UI with it, or with the one before.
    last_sign_in_at: datetime | None = None


class PasswordRepository(Protocol):
    def get(self, user_id: str) -> StoredPassword | None: ...

    def set(self, user_id: str, stored: StoredPassword) -> None: ...

    def signed_in(self, user_id: str, at: datetime) -> None: ...

    def delete(self, user_id: str) -> None: ...


class InMemoryPasswordRepository:
    def __init__(self) -> None:
        self._items: dict[str, StoredPassword] = {}

    def get(self, user_id: str) -> StoredPassword | None:
        return self._items.get(user_id)

    def set(self, user_id: str, stored: StoredPassword) -> None:
        self._items[user_id] = stored

    def signed_in(self, user_id: str, at: datetime) -> None:
        stored = self._items.get(user_id)
        if stored is not None:
            self._items[user_id] = replace(stored, last_sign_in_at=at)

    def delete(self, user_id: str) -> None:
        self._items.pop(user_id, None)
