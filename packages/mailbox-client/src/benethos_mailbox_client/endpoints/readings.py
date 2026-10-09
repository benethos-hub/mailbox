"""Readings every resource's endpoints share: a time of the API, a page
of records."""

from __future__ import annotations

from collections.abc import Callable
from datetime import datetime
from typing import Any, TypeVar

from ..models import Paged

R = TypeVar("R")


def time(value: Any) -> datetime:
    """A time of the API, ISO 8601 with its zone."""
    return datetime.fromisoformat(str(value))


def maybe_time(value: Any) -> datetime | None:
    """A time of the API that may be missing."""
    return time(value) if value else None


def paged(read: Callable[[dict[str, Any]], R]) -> Callable[[dict[str, Any]], Paged[R]]:
    """The reading of a page of records, each read by ``read``."""

    def reading(found: dict[str, Any]) -> Paged[R]:
        return Paged(
            items=[read(item) for item in found["items"]],
            next_cursor=found.get("next_cursor"),
        )

    return reading
