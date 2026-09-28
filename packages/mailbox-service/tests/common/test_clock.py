"""The clock and the local time of a line."""

from __future__ import annotations

from datetime import UTC, datetime, timedelta

from benethos_mailbox_service.common.clock import local_moment, utc_now


def test_utc_now_is_aware_and_in_utc() -> None:
    assert utc_now().utcoffset() == timedelta(0)


def test_a_moment_is_local_to_the_millisecond() -> None:
    value = datetime(2026, 9, 28, 10, 12, 22, 123456, tzinfo=UTC)
    local = value.astimezone()
    assert local_moment(value) == local.strftime("%Y-%m-%d %H:%M:%S") + ".123"
