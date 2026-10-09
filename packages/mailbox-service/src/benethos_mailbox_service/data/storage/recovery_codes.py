"""The recovery codes of users' second factors, as keyed hashes
(docs/AUTHENTICATION.md 6), each with the id of the data key its hash
came from. They belong to the second factor, not to one of its methods.

It only stores. The domain makes the codes and decides when they go.
"""

from __future__ import annotations

from datetime import datetime
from typing import Protocol


class RecoveryCodeRepository(Protocol):
    def replace(self, user_id: str, key_id: str, codes: list[str]) -> None:
        """The hashes of a new set, made with the data key ``key_id``, in
        place of any before."""
        ...

    def use(self, user_id: str, key_id: str, code: str, at: datetime) -> bool:
        """Mark the code with this hash, made with ``key_id``, used. False
        when the user has none such left."""
        ...

    def left(self, user_id: str) -> int: ...

    def delete(self, user_id: str) -> None: ...


class InMemoryRecoveryCodeRepository:
    def __init__(self) -> None:
        # Per user: the key of the set, and each hash to when it was used,
        # None while it is left.
        self._keys: dict[str, str] = {}
        self._codes: dict[str, dict[str, datetime | None]] = {}

    def replace(self, user_id: str, key_id: str, codes: list[str]) -> None:
        self._keys[user_id] = key_id
        self._codes[user_id] = dict.fromkeys(codes)

    def use(self, user_id: str, key_id: str, code: str, at: datetime) -> bool:
        codes = self._codes.get(user_id, {})
        if self._keys.get(user_id) != key_id:
            return False
        if code not in codes or codes[code] is not None:
            return False
        codes[code] = at
        return True

    def left(self, user_id: str) -> int:
        return sum(1 for used in self._codes.get(user_id, {}).values() if used is None)

    def delete(self, user_id: str) -> None:
        self._keys.pop(user_id, None)
        self._codes.pop(user_id, None)
