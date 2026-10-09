"""The recovery codes of a user's second factor: one set, standing in for
any of its methods (docs/AUTHENTICATION.md 6).

A code holds 75 bits. It is stored as a keyed hash, with the user's id
in what is hashed. The hash comes from outside: the domain knows no key.
The service hands in an HMAC under a key derived from the data key, so
whoever steals the database without the master key cannot try a single
guess.
"""

from __future__ import annotations

import secrets
from collections.abc import Callable
from datetime import datetime

from ...common.clock import utc_now
from ...data.storage import RecoveryCodeRepository

RECOVERY_CODES = 10
# Crockford's base32: no I, L, O or U, so nothing is mistaken for 1 or 0.
_ALPHABET = "0123456789ABCDEFGHJKMNPQRSTVWXYZ"
_GROUP = 5
_LENGTH = 3 * _GROUP
# What a person may type for a character of the alphabet.
_READ_AS = str.maketrans({"I": "1", "L": "1", "O": "0"})
# The purpose the key of the hashes is derived for.
HASH_LABEL = "recovery-code"

# A keyed hash of a text: the id of its key, and the hash.
KeyedHash = Callable[[str], tuple[str, str]]


def new_recovery_code() -> str:
    """Fifteen characters of 32, 75 bits, shown as three groups of five."""
    text = "".join(secrets.choice(_ALPHABET) for _ in range(_LENGTH))
    return "-".join(text[i : i + _GROUP] for i in range(0, _LENGTH, _GROUP))


def recovery_text(presented: str) -> str | None:
    """A recovery code as it is hashed. Case, spaces and dashes do not
    count. None for what cannot be one."""
    text = "".join(presented.split()).replace("-", "").upper().translate(_READ_AS)
    if len(text) != _LENGTH or any(c not in _ALPHABET for c in text):
        return None
    return text


class RecoveryCodes:
    def __init__(
        self,
        repository: RecoveryCodeRepository,
        keyed_hash: KeyedHash,
        clock: Callable[[], datetime] = utc_now,
    ) -> None:
        self._repository = repository
        self._keyed_hash = keyed_hash
        self._clock = clock

    def make(self, user_id: str) -> list[str]:
        """A new set in place of the old, to be shown once."""
        codes = [new_recovery_code() for _ in range(RECOVERY_CODES)]
        hashed = [self._hash(user_id, code.replace("-", "")) for code in codes]
        self._repository.replace(user_id, hashed[0][0], [h for _, h in hashed])
        return codes

    def use(self, user_id: str, presented: str) -> bool:
        """Whether ``presented`` is one of the user's codes left. It is used
        up."""
        text = recovery_text(presented)
        if text is None:
            return False
        key_id, hashed = self._hash(user_id, text)
        return self._repository.use(user_id, key_id, hashed, self._clock())

    def left(self, user_id: str) -> int:
        return self._repository.left(user_id)

    def delete(self, user_id: str) -> None:
        self._repository.delete(user_id)

    def _hash(self, user_id: str, text: str) -> tuple[str, str]:
        return self._keyed_hash(f"{user_id}:{text}")
