"""The figures of the service in the text format of Prometheus, for
`GET /v1/metrics`. The one module that imports prometheus_client.

An account is named by its id, its provider and its status, never by
its address, and no text of an error goes out. A point in time that
does not exist yet is no series at all, never 0. Beside it the alerts
on these figures, for Prometheus to load (``alert_rules``).
"""

from __future__ import annotations

from collections.abc import Iterator
from importlib import resources

from prometheus_client import CONTENT_TYPE_LATEST, generate_latest
from prometheus_client.core import (
    CounterMetricFamily,
    GaugeMetricFamily,
    InfoMetricFamily,
    Metric,
)
from prometheus_client.process_collector import ProcessCollector
from prometheus_client.registry import CollectorRegistry

from ...data.models import AccountStatus
from ...domain.sync import WorkerState
from ...domain.system import AccountHealth, Figures
from ...domain.webhooks import WebhookCounts

CONTENT_TYPE: str = CONTENT_TYPE_LATEST

_ACCOUNT = ["account", "provider"]


def alert_rules() -> str:
    """The alerts on the figures as a file of rules of Prometheus, kept
    beside this module so a renamed figure fails its test."""
    return (resources.files(__package__) / "alert_rules.yml").read_text("utf-8")


def exposition(figures: Figures, version: str) -> bytes:
    """The figures as the body of an answer, with the process's own
    figures where the system offers them (Linux)."""
    registry = CollectorRegistry()
    registry.register(_Collector(figures, version))
    ProcessCollector(registry=registry)
    return generate_latest(registry)


class _Collector:
    """Turns the figures into series, once per answer."""

    def __init__(self, figures: Figures, version: str) -> None:
        self._figures = figures
        self._version = version

    def collect(self) -> Iterator[Metric]:
        info = InfoMetricFamily("mailbox", "The version of the service")
        info.add_metric([], {"version": self._version})
        yield info
        yield from _worker(self._figures.worker)
        yield from _accounts(self._figures.accounts)
        yield from _webhooks(self._figures.webhooks)


def _gauge(name: str, documentation: str, value: float) -> GaugeMetricFamily:
    return GaugeMetricFamily(name, documentation, value=value)


def _worker(worker: WorkerState | None) -> Iterator[Metric]:
    yield _gauge(
        "mailbox_worker_enabled",
        "Whether the sync worker runs",
        0 if worker is None else 1,
    )
    if worker is None:
        return
    yield _gauge(
        "mailbox_worker_interval_seconds",
        "Seconds between two rounds over the accounts",
        worker.interval,
    )
    yield _gauge(
        "mailbox_worker_push",
        "Whether watchers wait for a server to report a change",
        int(worker.push),
    )
    yield _gauge(
        "mailbox_worker_watched_accounts",
        "Accounts a watcher waits on now",
        len(worker.watching),
    )
    if worker.last_pass_at is not None:
        yield _gauge(
            "mailbox_worker_last_round_timestamp_seconds",
            "When the last round over the accounts ended",
            worker.last_pass_at.timestamp(),
        )


def _accounts(healths: list[AccountHealth]) -> Iterator[Metric]:
    counts = GaugeMetricFamily(
        "mailbox_accounts", "Accounts by their status", labels=["status"]
    )
    for kind in AccountStatus:
        count = sum(1 for h in healths if h.account.status is kind)
        counts.add_metric([kind.value], count)
    yield counts
    yield _gauge(
        "mailbox_accounts_attention",
        "Accounts a person should look at",
        sum(1 for h in healths if h.attention),
    )
    status = GaugeMetricFamily(
        "mailbox_account_status",
        "The status of an account, one series each",
        labels=[*_ACCOUNT, "status"],
    )
    attention = GaugeMetricFamily(
        "mailbox_account_attention",
        "Whether a person should look at the account",
        labels=_ACCOUNT,
    )
    synced = GaugeMetricFamily(
        "mailbox_account_synced",
        "Whether a sync pass does anything for the account",
        labels=_ACCOUNT,
    )
    last_sync = GaugeMetricFamily(
        "mailbox_account_last_sync_timestamp_seconds",
        "When the last pass of the account succeeded, since the start",
        labels=_ACCOUNT,
    )
    outbox = GaugeMetricFamily(
        "mailbox_account_outbox",
        "Sends of the account's outbox: waiting, and failed or of unknown "
        "outcome in the last 24 hours",
        labels=[*_ACCOUNT, "state"],
    )
    passes = CounterMetricFamily(
        "mailbox_account_sync_passes",
        "Passes of the account that succeeded, since the start",
        labels=_ACCOUNT,
    )
    for health in healths:
        account = health.account
        names = [account.id, account.provider.value]
        status.add_metric([*names, account.status.value], 1)
        attention.add_metric(names, int(health.attention))
        synced.add_metric(names, int(health.synced))
        if health.sync.last_sync_at is not None:
            last_sync.add_metric(names, health.sync.last_sync_at.timestamp())
        if health.synced:
            passes.add_metric(names, health.sync.passes)
        held = health.outbox
        for state, count in (
            ("queued", held.queued),
            ("failed", held.failed),
            ("unknown", held.unknown),
        ):
            outbox.add_metric([*names, state], count)
    yield from (status, attention, synced, last_sync, passes, outbox)
    yield _gauge(
        "mailbox_outbox_unknown",
        "Sends of the last 24 hours whose outcome is unknown",
        sum(h.outbox.unknown for h in healths),
    )


def _webhooks(counts: WebhookCounts) -> Iterator[Metric]:
    yield _gauge("mailbox_webhooks", "Webhooks of every user", counts.total)
    yield _gauge(
        "mailbox_webhooks_failing",
        "Webhooks whose last post failed",
        counts.failing,
    )
