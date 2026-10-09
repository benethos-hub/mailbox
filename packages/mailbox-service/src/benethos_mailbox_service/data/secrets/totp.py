"""Time-based one-time passwords, RFC 6238, as every authenticator app
reads them: HMAC-SHA1, six digits, a step of 30 seconds
(docs/AUTHENTICATION.md 2).

The standard library does all of it. A code is the HOTP of RFC 4226 for
the number of steps since 1970. One step either way is taken as well, for
the clocks of the server and the phone.
"""

from __future__ import annotations

import base64
import hashlib
import hmac
import secrets
import struct
from datetime import datetime
from urllib.parse import quote, urlencode

DIGITS = 6
STEP_SECONDS = 30
# 160 bits, the length of an HMAC-SHA1 key, as RFC 4226 recommends.
SECRET_BYTES = 20
# Steps taken before and after the current one.
DRIFT = 1


def new_secret() -> bytes:
    return secrets.token_bytes(SECRET_BYTES)


def base32(secret: bytes) -> str:
    """The secret as an app takes it typed in: base32, without padding."""
    return base64.b32encode(secret).decode("ascii").rstrip("=")


def from_base32(written: str) -> bytes:
    """The secret back from what ``base32`` wrote."""
    return base64.b32decode(written + "=" * (-len(written) % 8))


def step_of(at: datetime) -> int:
    """The number of whole steps since 1970 at ``at``."""
    return int(at.timestamp()) // STEP_SECONDS


def code(secret: bytes, step: int) -> str:
    """The code of a step: RFC 4226 with the step as the counter."""
    mac = hmac.new(secret, struct.pack(">Q", step), hashlib.sha1).digest()
    offset = mac[-1] & 0x0F
    number = struct.unpack(">I", mac[offset : offset + 4])[0] & 0x7FFFFFFF
    return str(number % 10**DIGITS).zfill(DIGITS)


def matching_step(
    secret: bytes, presented: str, at: datetime, after: int | None = None
) -> int | None:
    """The step whose code ``presented`` is, within ``DRIFT`` steps of
    ``at``. None when it is none of them, or when its step is not later
    than ``after``, the step of the last code taken: each code works
    once."""
    presented = presented.strip()
    if len(presented) != DIGITS or not presented.isdigit():
        return None
    now = step_of(at)
    for step in range(now - DRIFT, now + DRIFT + 1):
        if after is not None and step <= after:
            continue
        if hmac.compare_digest(code(secret, step), presented):
            return step
    return None


def uri(secret: bytes, issuer: str, account: str) -> str:
    """The ``otpauth://`` URI a QR code carries to the app. The label is
    ``issuer:account``, the issuer named again as a parameter, as the
    apps expect."""
    label = quote(f"{issuer}:{account}", safe=":@")
    query = urlencode(
        {
            "secret": base32(secret),
            "issuer": issuer,
            "algorithm": "SHA1",
            "digits": DIGITS,
            "period": STEP_SECONDS,
        },
        quote_via=quote,
    )
    return f"otpauth://totp/{label}?{query}"
