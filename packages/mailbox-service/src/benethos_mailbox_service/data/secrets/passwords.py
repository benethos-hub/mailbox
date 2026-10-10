"""Password hashes: scrypt from the standard library (CONCEPT 7.5).

A hash names its parameters, so one made with older parameters still
verifies and can be made anew at the next sign-in. The text is normalised
to NFKC first, so the same password typed on another keyboard matches.
"""

from __future__ import annotations

import hashlib
import hmac
import secrets
import unicodedata
from dataclasses import dataclass

from ...common.opaque import from_base64, to_base64

SCHEME = "scrypt"
SALT_BYTES = 16
KEY_BYTES = 32


@dataclass(frozen=True, slots=True)
class Scrypt:
    """Cost of one hash. The default is one of OWASP's scrypt settings:
    32 MiB of memory."""

    log_n: int = 15
    r: int = 8
    p: int = 3


class PasswordHasher:
    def __init__(self, cost: Scrypt | None = None) -> None:
        self._cost = cost or Scrypt()
        # Checked for a name nobody has, so it takes as long as a real one.
        self._dummy: str | None = None

    def hash(self, password: str) -> str:
        """``scrypt$ln=15,r=8,p=3$<salt>$<key>``, salt and key in base64."""
        cost = self._cost
        salt = secrets.token_bytes(SALT_BYTES)
        key = _derive(password, salt, cost)
        params = f"ln={cost.log_n},r={cost.r},p={cost.p}"
        encoded = f"{to_base64(salt, url=False)}${to_base64(key, url=False)}"
        return f"{SCHEME}${params}${encoded}"

    def verify(self, password: str, stored: str) -> bool:
        """Whether ``password`` is the one behind ``stored``. False for a
        hash this module cannot read."""
        parsed = _parse(stored)
        if parsed is None:
            return False
        cost, salt, key = parsed
        return hmac.compare_digest(_derive(password, salt, cost), key)

    def needs_rehash(self, stored: str) -> bool:
        """Whether ``stored`` was made with other parameters than today's."""
        parsed = _parse(stored)
        return parsed is None or parsed[0] != self._cost

    def verify_nothing(self, password: str) -> None:
        """Does the work of a check for a user that does not exist."""
        if self._dummy is None:
            self._dummy = self.hash(secrets.token_urlsafe(16))
        self.verify(password, self._dummy)


def _derive(password: str, salt: bytes, cost: Scrypt) -> bytes:
    n = 2**cost.log_n
    return hashlib.scrypt(
        unicodedata.normalize("NFKC", password).encode("utf-8"),
        salt=salt,
        n=n,
        r=cost.r,
        p=cost.p,
        # What OpenSSL needs for these parameters, and a little room.
        maxmem=128 * cost.r * (n + cost.p + 2) + 1024 * 1024,
        dklen=KEY_BYTES,
    )


def _parse(stored: str) -> tuple[Scrypt, bytes, bytes] | None:
    """Cost, salt and key of a hash, None when it is not one of ours or
    its cost is out of bounds."""
    try:
        scheme, params, salt, key = stored.split("$")
        values = dict(item.split("=", 1) for item in params.split(","))
        cost = Scrypt(log_n=int(values["ln"]), r=int(values["r"]), p=int(values["p"]))
        parsed = (
            cost,
            from_base64(salt, url=False),
            from_base64(key, url=False),
        )
    except (ValueError, KeyError):
        return None
    in_bounds = 1 <= cost.log_n <= 20 and 1 <= cost.r <= 32 and 1 <= cost.p <= 16
    return parsed if scheme == SCHEME and in_bounds else None
