"""Opaque values handed to callers: ids and cursors that carry a little JSON.

A prefix names the kind, the rest is URL-safe base64 without padding. Only
the code that made a value reads it back. To a caller it is a string.
The base64 without padding is offered to the others who write it: a
password hash in the standard alphabet, PKCE and an ID token in the
URL-safe one.
"""

from __future__ import annotations

import base64
import json
from typing import Any

from benethos_mailbox_common.values import canonical

_URL_SAFE = b"-_"


def to_base64(data: bytes, *, url: bool = True) -> str:
    """``data`` in base64 without padding, in the URL-safe alphabet unless
    ``url`` is false."""
    return base64.b64encode(data, _URL_SAFE if url else None).decode().rstrip("=")


def from_base64(text: str, *, url: bool = True) -> bytes:
    """The bytes ``to_base64`` wrote, with or without padding.
    ``ValueError`` when ``text`` is not base64 of that alphabet."""
    padded = text + "=" * (-len(text) % 4)
    return base64.b64decode(padded, _URL_SAFE if url else None, validate=True)


def encode(prefix: str, value: object) -> str:
    raw = canonical.compact(value).encode()
    return prefix + to_base64(raw)


def decode(prefix: str, token: str) -> Any:
    """The value inside ``token``. ``ValueError`` when it is not one of ours."""
    if not token.startswith(prefix):
        raise ValueError(f"not a {prefix} value")
    try:
        return json.loads(from_base64(token[len(prefix) :]))
    except (ValueError, UnicodeDecodeError):
        raise ValueError(f"not a {prefix} value") from None


def fields(prefix: str, token: str, *kinds: type) -> list[Any] | None:
    """The parts inside ``token`` when it holds a list of as many parts as
    ``kinds``, each of its kind, else None. An ``int`` part is never a
    ``bool`` and never below 0: it counts or numbers something."""
    try:
        parts = decode(prefix, token)
    except ValueError:
        return None
    if not isinstance(parts, list) or len(parts) != len(kinds):
        return None
    for part, kind in zip(parts, kinds, strict=True):
        if not isinstance(part, kind):
            return None
        if isinstance(part, int) and (isinstance(part, bool) or part < 0):
            return None
    return parts
