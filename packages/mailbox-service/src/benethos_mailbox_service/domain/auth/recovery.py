"""The recovery codes of a user's second factor: one set, standing in for
any of its methods (docs/AUTHENTICATION.md 6)."""

from __future__ import annotations

import secrets
from collections.abc import Callable
from datetime import datetime

from ...common.clock import utc_now
from ...common.secret import digest
from ...data.storage import RecoveryCodeRepository

RECOVERY_CODES = 10
# Crockford's base32: no I, L, O or U, so nothing is mistaken for 1 or 0.
_ALPHABET = "0123456789ABCDEFGHJKMNPQRSTVWXYZ"
_GROUP = 5
_LENGTH = 2 * _GROUP
# What a person may type for a character of the alphabet.
_READ_AS = str.maketrans({"I": "1", "L": "1", "O": "0"})


def new_recovery_code() -> str:
    """Ten characters of 32, 50 bits, shown as two groups of five."""
    text = "".join(secrets.choice(_ALPHABET) for _ in range(_LENGTH))
    return f"{text[:_GROUP]}-{text[_GROUP:]}"


def recovery_hash(presented: str) -> str | None:
    """The hash a recovery code is stored as. Case, spaces and dashes do
    not count. None for what cannot be one."""
    text = "".join(presented.split()).replace("-", "").upper().translate(_READ_AS)
    if len(text) != _LENGTH or any(c not in _ALPHABET for c in text):
        return None
    return digest(text)


class RecoveryCodes:
    def __init__(
        self,
        repository: RecoveryCodeRepository,
        clock: Callable[[], datetime] = utc_now,
    ) -> None:
        self._repository = repository
        self._clock = clock

    def make(self, user_id: str) -> list[str]:
        """A new set in place of the old, to be shown once."""
        codes = [new_recovery_code() for _ in range(RECOVERY_CODES)]
        self._repository.replace(user_id, [_hashed(code) for code in codes])
        return codes

    def use(self, user_id: str, presented: str) -> bool:
        """Whether ``presented`` is one of the user's codes left. It is used
        up."""
        hashed = recovery_hash(presented)
        return hashed is not None and self._repository.use(
            user_id, hashed, self._clock()
        )

    def left(self, user_id: str) -> int:
        return self._repository.left(user_id)

    def delete(self, user_id: str) -> None:
        self._repository.delete(user_id)


def _hashed(code: str) -> str:
    """The hash of a code made here, which is always one."""
    return digest(code.replace("-", ""))
