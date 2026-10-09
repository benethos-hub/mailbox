"""The second factor of a user: a TOTP secret and its recovery codes
(docs/AUTHENTICATION.md).

This module checks a code and keeps what goes with a factor. Who may
set one up or remove it is decided in ``domain/users/factors.py``, the
sign-in with it in ``AuthService``.
"""

from __future__ import annotations

import secrets
from collections.abc import Callable
from datetime import datetime, timedelta
from typing import Literal

from pydantic import SecretStr

from ...common.clock import utc_now
from ...common.secret import digest
from ...data.secrets import CredentialVault, totp
from ...data.storage import SecondFactorRepository, StoredFactor

# How a code at the sign-in was taken.
Kind = Literal["totp", "recovery"]

# A pending sign-in, between the password and the code, ends after this,
# or after this many wrong codes.
PENDING = timedelta(minutes=5)
CODE_TRIES = 5
# A secret shown for setup and not yet confirmed is dropped after this.
SETUP = timedelta(minutes=15)

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


class SecondFactors:
    """The factors of every user: made, checked, removed."""

    def __init__(
        self,
        repository: SecondFactorRepository,
        vault: CredentialVault,
        clock: Callable[[], datetime] = utc_now,
    ) -> None:
        self._repository = repository
        self._vault = vault
        self._clock = clock

    def has(self, user_id: str) -> bool:
        return self._repository.get(user_id) is not None

    def stamp(self, user_id: str) -> datetime | None:
        """When the user's factor was confirmed. A session keeps it and
        ends once the factor is set up anew or removed."""
        stored = self._repository.get(user_id)
        return stored.confirmed_at if stored is not None else None

    def codes_left(self, user_id: str) -> int:
        return self._repository.codes_left(user_id)

    def check(self, user_id: str, presented: str) -> Kind | None:
        """Whether ``presented`` is a code of the user's app not taken
        before, or one of its recovery codes left. Either is used up."""
        stored = self._repository.get(user_id)
        if stored is None:
            return None
        if presented.strip().isdigit():
            secret = self._unsealed(user_id, stored)
            step = totp.matching_step(
                secret, presented, self._clock(), after=stored.last_step
            )
            if step is not None and self._repository.took(user_id, step):
                return "totp"
            return None
        hashed = recovery_hash(presented)
        if hashed is not None and self._repository.use_code(
            user_id, hashed, self._clock()
        ):
            return "recovery"
        return None

    def confirm(self, user_id: str, secret: bytes, presented: str) -> list[str] | None:
        """Store ``secret`` as the user's factor once ``presented`` is its
        code now. Returns the new recovery codes, to be shown once. None
        when the code is not right."""
        step = totp.matching_step(secret, presented, self._clock())
        if step is None:
            return None
        sealed = self._vault.seal(_label(user_id), SecretStr(totp.base32(secret)))
        codes = [new_recovery_code() for _ in range(RECOVERY_CODES)]
        self._repository.set(
            user_id,
            StoredFactor(sealed, self._clock(), last_step=step),
            [_hashed(code) for code in codes],
        )
        return codes

    def renew_codes(self, user_id: str) -> list[str]:
        """A new set of recovery codes in place of the old."""
        codes = [new_recovery_code() for _ in range(RECOVERY_CODES)]
        self._repository.replace_codes(user_id, [_hashed(code) for code in codes])
        return codes

    def remove(self, user_id: str) -> bool:
        """The factor and its codes. False when the user had none."""
        return self._repository.delete(user_id)

    def _unsealed(self, user_id: str, stored: StoredFactor) -> bytes:
        written = self._vault.unseal(_label(user_id), stored.secret)
        return totp.from_base32(written.get_secret_value())


def _label(user_id: str) -> str:
    """What the sealed secret is bound to: one user's factor."""
    return f"totp:{user_id}"


def _hashed(code: str) -> str:
    """The hash of a code made here, which is always one."""
    return digest(code.replace("-", ""))
