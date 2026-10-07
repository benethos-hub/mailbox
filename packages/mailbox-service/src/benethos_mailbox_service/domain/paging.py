"""The cursors this service hands out itself, read back from a caller, and
the page they continue."""

from __future__ import annotations

from collections.abc import Callable, Iterable
from dataclasses import dataclass
from datetime import datetime
from typing import Any, Generic, TypeVar

from ..common import opaque
from ..common.clock import iso, parse_iso
from ..data.models import Before, Page
from ..errors import BadRequestError

T = TypeVar("T")

INVALID = "invalid cursor"

# The sort key of an item: what a cursor carries, so plain JSON values.
Key = tuple[str | int, ...]


@dataclass(frozen=True)
class Order(Generic[T]):
    """The order a list is paged in. ``prefix`` tells its cursors apart
    from those of other lists. ``key`` ranks the items and is unique per
    item, so an id comes last."""

    prefix: str
    key: Callable[[T], Key]


def page(
    items: Iterable[T], order: Order[T], *, limit: int, cursor: str | None
) -> Page[T]:
    """The page of ``items`` in ``order`` that ``cursor`` continues, for a
    list held whole. The cursor carries the key of the last item shown,
    so an item added or removed in between does not shift the next page."""
    ranked = sorted(items, key=order.key)
    if cursor is not None:
        after = decode_cursor(order.prefix, cursor, _key)
        try:
            ranked = [item for item in ranked if order.key(item) > after]
        except TypeError:  # a key of another shape, of another order
            raise BadRequestError(INVALID) from None
    shown, more = split_page(ranked, limit)
    next_cursor = encode_cursor(order.prefix, order.key(shown[-1])) if more else None
    return Page[T](items=shown, next_cursor=next_cursor)


def _key(carried: Any) -> Key:
    if not isinstance(carried, list) or not all(
        isinstance(part, str | int) and not isinstance(part, bool) for part in carried
    ):
        raise ValueError("not a sort key")
    return tuple(carried)


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


def encode_before(prefix: str, at: datetime, record_id: str) -> str:
    """The cursor after a record of a list newest first: its time and id."""
    return encode_cursor(prefix, [iso(at), record_id])


def decode_before(prefix: str, value: str | None) -> Before | None:
    """Where the cursor ``encode_before`` made continues. None without
    one, the first page."""
    if value is None:
        return None
    return decode_cursor(prefix, value, _before_of)


def _before_of(carried: Any) -> Before:
    at, record_id = carried
    return Before(parse_iso(str(at)), str(record_id))


def split_page(found: list[T], limit: int) -> tuple[list[T], bool]:
    """The first ``limit`` of ``found``, and whether there are more. The
    caller asks its store for ``limit + 1``."""
    return found[:limit], len(found) > limit
