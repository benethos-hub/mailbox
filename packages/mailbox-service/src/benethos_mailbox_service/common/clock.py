"""The time of day, for records and expiry. Services take a clock as a
parameter with this as the default, so tests can set the time."""

from __future__ import annotations

from datetime import UTC, datetime


def utc_now() -> datetime:
    return datetime.now(UTC)
