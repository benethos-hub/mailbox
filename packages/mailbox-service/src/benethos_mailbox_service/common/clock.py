"""The time of day, for records and expiry. Services take a clock as a
parameter with this as the default, so tests can set the time."""

from __future__ import annotations

from datetime import UTC, datetime


def utc_now() -> datetime:
    return datetime.now(UTC)


def local_moment(value: datetime) -> str:
    """Date and time to the millisecond, in the local time of this machine
    and without the offset, as a person at it reads a line of the log."""
    local = value.astimezone()
    return f"{local:%Y-%m-%d %H:%M:%S}.{local.microsecond // 1000:03d}"
