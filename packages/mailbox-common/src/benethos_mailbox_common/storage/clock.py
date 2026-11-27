"""Times as a database keeps them: as text in UTC, so that times compare
as text, in a column, a cursor or a stored state."""

from __future__ import annotations

from datetime import UTC, datetime
from typing import overload


def utc_now() -> datetime:
    return datetime.now(UTC)


@overload
def iso(value: datetime) -> str: ...
@overload
def iso(value: None) -> None: ...
@overload
def iso(value: datetime | None) -> str | None: ...
def iso(value: datetime | None) -> str | None:
    """A time as text, in UTC, so that times compare as text: in a
    column of the database, a cursor or a stored state. A time without a
    zone is refused."""
    if value is None:
        return None
    if value.tzinfo is None:
        raise ValueError("a time without a zone cannot be stored")
    return value.astimezone(UTC).isoformat()


@overload
def parse_iso(value: str) -> datetime: ...
@overload
def parse_iso(value: None) -> None: ...
@overload
def parse_iso(value: str | None) -> datetime | None: ...
def parse_iso(value: str | None) -> datetime | None:
    """The time ``iso`` wrote, None for none."""
    return datetime.fromisoformat(value) if value else None
