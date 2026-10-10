"""The time of day, for records and expiry. Services take a clock as a
parameter with this as the default, so tests can set the time."""

from __future__ import annotations

from datetime import UTC, date, datetime, time
from typing import overload


def utc_now() -> datetime:
    return datetime.now(UTC)


def start_of_day(day: date) -> datetime:
    """Midnight at the start of ``day`` in the local time of this machine,
    the time the UI shows."""
    return datetime.combine(day, time()).astimezone()


def parse_day(value: str) -> datetime | None:
    """The start of the day ``value`` names, such as ``2026-10-07``, as
    ``start_of_day``. None for no value. Raises ``ValueError`` for text
    that names no day."""
    return start_of_day(date.fromisoformat(value)) if value else None


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
