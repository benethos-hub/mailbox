"""The time of day, for records and expiry. Services take a clock as a
parameter with this as the default, so tests can set the time."""

from __future__ import annotations

from datetime import UTC, datetime
from typing import overload


def utc_now() -> datetime:
    return datetime.now(UTC)


def local_moment(value: datetime) -> str:
    """Date and time to the millisecond, in the local time of this machine
    and without the offset, as a person at it reads a line of the log."""
    local = value.astimezone()
    return f"{local:%Y-%m-%d %H:%M:%S}.{local.microsecond // 1000:03d}"


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
