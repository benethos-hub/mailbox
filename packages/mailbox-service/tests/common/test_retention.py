"""When old records are due to go."""

from __future__ import annotations

from datetime import UTC, datetime, timedelta

from benethos_mailbox_service.common.retention import PURGE_EVERY, Retention

NOW = datetime(2026, 10, 7, 12, 0, tzinfo=UTC)


def test_the_first_purge_is_due_at_once_then_once_per_period() -> None:
    retention = Retention(7)
    assert retention.due(NOW)
    retention.done(NOW)
    assert not retention.due(NOW + PURGE_EVERY - timedelta(seconds=1))
    assert retention.due(NOW + PURGE_EVERY)


def test_the_cutoff_is_the_days_back() -> None:
    assert Retention(7).cutoff(NOW) == NOW - timedelta(days=7)


def test_zero_days_keeps_every_record() -> None:
    retention = Retention(0)
    assert retention.days == 0
    assert not retention.due(NOW)


def test_the_period_is_a_setting() -> None:
    retention = Retention(1, every=timedelta(minutes=5))
    retention.done(NOW)
    assert retention.due(NOW + timedelta(minutes=5))
