"""The time of day, for records and expiry. Services take a clock as a
parameter with this as the default, so tests can set the time."""

from __future__ import annotations

from datetime import date, datetime, time

from benethos_mailbox_common.storage import clock

# As a database keeps a time, in UTC, so that times compare as text.
iso = clock.iso
parse_iso = clock.parse_iso
utc_now = clock.utc_now


def start_of_day(day: date) -> datetime:
    """Midnight at the start of ``day`` in the local time of this machine,
    the time the UI shows."""
    return datetime.combine(day, time()).astimezone()


def parse_day(value: str) -> datetime | None:
    """The start of the day ``value`` names, such as ``2026-10-07``, as
    ``start_of_day``. None for no value. Raises ``ValueError`` for text
    that names no day."""
    return start_of_day(date.fromisoformat(value)) if value else None


def parse_local(value: str) -> datetime | None:
    """A date and a time as a browser's field sends them, such as
    ``2026-10-07T18:30``: without a zone, the local time of this machine.
    None for no value. Raises ``ValueError`` for text that names none."""
    return datetime.fromisoformat(value).astimezone() if value else None
