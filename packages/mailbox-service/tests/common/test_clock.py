"""The clock and the local time of a line."""

from __future__ import annotations

from datetime import UTC, datetime, timedelta, timezone

import pytest

from benethos_mailbox_service.common.clock import (
    iso,
    log_time,
    parse_iso,
    utc_now,
)


def test_utc_now_is_aware_and_in_utc() -> None:
    assert utc_now().utcoffset() == timedelta(0)


def test_a_log_time_is_iso_local_to_the_millisecond_with_the_offset() -> None:
    value = datetime(2026, 9, 28, 10, 12, 22, 123456, tzinfo=UTC)
    local = value.astimezone()
    offset = local.isoformat()[-6:]
    assert log_time(value) == f"{local:%Y-%m-%dT%H:%M:%S}.123{offset}"
    assert datetime.fromisoformat(log_time(value)) == value.replace(microsecond=123000)


def test_a_time_as_text_is_in_utc_and_read_back() -> None:
    value = datetime(2026, 9, 28, 12, 0, tzinfo=timezone(timedelta(hours=2)))
    assert iso(value) == "2026-09-28T10:00:00+00:00"
    assert parse_iso(iso(value)) == value
    assert iso(None) is None
    assert parse_iso(None) is None


def test_a_time_without_a_zone_is_refused() -> None:
    with pytest.raises(ValueError, match="without a zone"):
        iso(datetime(2026, 9, 28, 12, 0))
