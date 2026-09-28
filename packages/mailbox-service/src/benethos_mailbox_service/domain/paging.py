"""The cursors this service hands out itself, read back from a caller, and
the page they continue."""

from __future__ import annotations

from collections.abc import Callable
from typing import Any, TypeVar

from ..common import opaque
from ..errors import BadRequestError

T = TypeVar("T")

INVALID = "invalid cursor"


def encode_cursor(prefix: str, value: object) -> str:
    """A cursor that carries ``value``, opaque to the caller."""
    return opaque.encode(prefix, value)


def decode_cursor(
    prefix: str,
    value: str,
    parse: Callable[[Any], T] = lambda carried: carried,
    *,
    refusal: str = INVALID,
) -> T:
    """What the cursor carries, read by ``parse``. A cursor is a request
    parameter: one the service did not hand out, or one ``parse`` cannot
    read, is a bad request with ``refusal``, not something missing."""
    try:
        return parse(opaque.decode(prefix, value))
    except (ValueError, TypeError, KeyError, AttributeError):
        raise BadRequestError(refusal) from None


def split_page(found: list[T], limit: int) -> tuple[list[T], bool]:
    """The first ``limit`` of ``found``, and whether there are more. The
    caller asks its store for ``limit + 1``."""
    return found[:limit], len(found) > limit
