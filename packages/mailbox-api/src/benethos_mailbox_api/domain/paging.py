"""The cursors this service hands out itself, read back from a caller."""

from __future__ import annotations

from typing import Any

from ..common import opaque
from ..errors import BadRequestError


def decode_cursor(prefix: str, value: str) -> Any:
    """What the cursor carries. A cursor is a request parameter: one the
    service did not hand out is a bad request, not something missing."""
    try:
        return opaque.decode(prefix, value)
    except ValueError:
        raise BadRequestError("invalid cursor") from None
