"""Opaque values handed to callers: ids and cursors that carry a little JSON.

A prefix names the kind, the rest is URL-safe base64 without padding. Only
the code that made a value reads it back; to a caller it is a string.
"""

from __future__ import annotations

import base64
import binascii
import json
from typing import Any


def encode(prefix: str, value: object) -> str:
    raw = json.dumps(value, separators=(",", ":"), ensure_ascii=False).encode()
    return prefix + base64.urlsafe_b64encode(raw).decode().rstrip("=")


def decode(prefix: str, token: str) -> Any:
    """The value inside ``token``. ``ValueError`` when it is not one of ours."""
    if not token.startswith(prefix):
        raise ValueError(f"not a {prefix} value")
    text = token[len(prefix) :]
    try:
        return json.loads(base64.urlsafe_b64decode(text + "=" * (-len(text) % 4)))
    except (binascii.Error, ValueError, UnicodeDecodeError):
        raise ValueError(f"not a {prefix} value") from None
