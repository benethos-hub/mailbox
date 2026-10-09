"""Second factors of users: the TOTP secret, sealed, and the hashes of the
recovery codes (docs/AUTHENTICATION.md 6).

It only stores. The domain makes the secret and the codes, and decides
who may set up or remove a factor.
"""

from __future__ import annotations

from dataclasses import dataclass, replace
from datetime import datetime
from typing import Protocol

from .webhooks import Sealed


@dataclass(frozen=True)
class StoredFactor:
    """A confirmed TOTP secret. ``last_step`` is the step of the last code
    taken, none before the first sign-in with it."""

    secret: Sealed
    confirmed_at: datetime
    last_step: int | None = None


class SecondFactorRepository(Protocol):
    def get(self, user_id: str) -> StoredFactor | None: ...

    def set(self, user_id: str, factor: StoredFactor, codes: list[str]) -> None:
        """The factor and the hashes of its recovery codes, in place of
        any before."""
        ...

    def took(self, user_id: str, step: int) -> bool:
        """Note a code of ``step`` as taken. False when a code of that
        step or a later one was taken already: two requests with the same
        code cannot both pass."""
        ...

    def replace_codes(self, user_id: str, codes: list[str]) -> None: ...

    def use_code(self, user_id: str, code: str, at: datetime) -> bool:
        """Mark the recovery code with this hash used. False when the user
        has none such left."""
        ...

    def codes_left(self, user_id: str) -> int: ...

    def delete(self, user_id: str) -> bool:
        """The factor and its codes. False when the user had none."""
        ...


class InMemorySecondFactorRepository:
    def __init__(self) -> None:
        self._factors: dict[str, StoredFactor] = {}
        # Per user: hash to when it was used, None while it is left.
        self._codes: dict[str, dict[str, datetime | None]] = {}

    def get(self, user_id: str) -> StoredFactor | None:
        return self._factors.get(user_id)

    def set(self, user_id: str, factor: StoredFactor, codes: list[str]) -> None:
        self._factors[user_id] = factor
        self.replace_codes(user_id, codes)

    def took(self, user_id: str, step: int) -> bool:
        factor = self._factors.get(user_id)
        if factor is None:
            return False
        if factor.last_step is not None and factor.last_step >= step:
            return False
        self._factors[user_id] = replace(factor, last_step=step)
        return True

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
        return self._factors.pop(user_id, None) is not None
