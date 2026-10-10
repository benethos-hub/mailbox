"""Random values and their digests: the ids of records, secrets to hand
out, and the hashes and signatures made of them. Every random value
comes from the operating system's secure source.

How long a random value is stands here, with the reason:

- 32 bytes, 256 bits (``STRONG``): an id, a session, a sign-in, a
  webhook's secret. Nobody can guess one or count through them.
- 24 bytes, 192 bits (``SHORT``): a value that lives for one form or one
  page, such as the nonce of the sign-in page or the key of a send form.
- A protocol or a person may need another length: the caller names it,
  such as the PKCE verifier or a one-time password.
"""

from __future__ import annotations

import hashlib
import hmac
import secrets

STRONG = 32
SHORT = 24


def new_id(prefix: str) -> str:
    """``prefix``, an underscore and 64 hex digits. The caller owns the
    prefix, such as ``acc``."""
    return f"{prefix}_{secrets.token_hex(STRONG)}"


def token(size: int = STRONG) -> str:
    """``size`` random bytes as URL-safe text, about 1.3 characters each."""
    return secrets.token_urlsafe(size)


def digest(text: str) -> str:
    """The SHA-256 of ``text`` as UTF-8, in hex: to store a token without
    the token, or to compare what was asked."""
    return hashlib.sha256(text.encode()).hexdigest()


def hmac_hex(secret: str, data: bytes) -> str:
    """The HMAC-SHA256 of ``data`` with ``secret``, in hex."""
    return hmac.new(secret.encode(), data, hashlib.sha256).hexdigest()


def same(presented: str, expected: str) -> bool:
    """Whether two secrets are equal, in a time that does not tell how
    much of them matched."""
    return hmac.compare_digest(presented.encode(), expected.encode())
