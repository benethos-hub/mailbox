"""The recovery codes of users' second factors, as hashes
(docs/AUTHENTICATION.md 6). They belong to the second factor, not to
one of its methods.

It only stores. The domain makes the codes and decides when they go.
"""

from __future__ import annotations

from datetime import datetime
from typing import Protocol


class RecoveryCodeRepository(Protocol):
    def replace(self, user_id: str, codes: list[str]) -> None:
        """The hashes of a new set, in place of any before."""
        ...

    def use(self, user_id: str, code: str, at: datetime) -> bool:
        """Mark the code with this hash used. False when the user has none
        such left."""
        ...

    def left(self, user_id: str) -> int: ...

    def delete(self, user_id: str) -> None: ...


class InMemoryRecoveryCodeRepository:
    def __init__(self) -> None:
        # Per user: hash to when it was used, None while it is left.
        self._codes: dict[str, dict[str, datetime | None]] = {}

    def replace(self, user_id: str, codes: list[str]) -> None:
        self._codes[user_id] = dict.fromkeys(codes)

    def use(self, user_id: str, code: str, at: datetime) -> bool:
        codes = self._codes.get(user_id, {})
        if code not in codes or codes[code] is not None:
            return False
        codes[code] = at
        return True

    def left(self, user_id: str) -> int:
        return sum(1 for used in self._codes.get(user_id, {}).values() if used is None)

    def delete(self, user_id: str) -> None:
        self._codes.pop(user_id, None)
