"""The figures of the service in the text format of Prometheus, without
HTTP (`web/api/exposition.py`)."""

from __future__ import annotations

from datetime import UTC, datetime

from benethos_mailbox_service.data.models import Account, AccountStatus, ProviderType
from benethos_mailbox_service.domain.sync import SyncState, WorkerState
from benethos_mailbox_service.domain.system import AccountHealth, Figures
from benethos_mailbox_service.domain.webhooks import WebhookCounts
from benethos_mailbox_service.web.api.exposition import CONTENT_TYPE, exposition

AT = datetime(2026, 11, 22, 12, tzinfo=UTC)
SECONDS = AT.timestamp()

IMAP = Account(
    id="acc_1",
    provider=ProviderType.IMAP,
    email="first@example.org",
    display_name="Tinkerbell Account",
)
GMAIL = Account(
    id="acc_2",
    provider=ProviderType.GMAIL,
    email="second@example.org",
    status=AccountStatus.NEEDS_REAUTH,
)
WORKER = WorkerState(
    interval=300,
    push=True,
    last_pass_at=AT,
    watching=frozenset({"acc_1"}),
    watchers=50,
)
NO_WEBHOOKS = WebhookCounts(total=0, failing=0)


def figures(
    *healths: AccountHealth,
    worker: WorkerState | None = WORKER,
    webhooks: WebhookCounts = NO_WEBHOOKS,
) -> Figures:
    return Figures(accounts=list(healths), worker=worker, webhooks=webhooks)


def series(text: str) -> dict[str, float]:
    """Each line of a series, its name and labels, and its value."""
    found = {}
    for line in text.splitlines():
        if line and not line.startswith("#"):
            name, value = line.rsplit(" ", 1)
            found[name] = float(value)
    return found


def lines(f: Figures) -> dict[str, float]:
    return series(exposition(f, "0.9.0").decode())


def test_every_series_with_its_value() -> None:
    synced = AccountHealth(
        IMAP, SyncState(last_sync_at=AT, passes=3), synced=True, watching=True
    )
    failing = AccountHealth(
        GMAIL,
        SyncState(passes=1, last_error="Ladybird failed", last_error_at=AT),
        synced=True,
        watching=False,
    )
    found = lines(figures(synced, failing, webhooks=WebhookCounts(total=2, failing=1)))
    imap = 'account="acc_1",provider="imap"'
    gmail = 'account="acc_2",provider="gmail"'
    assert found == {
        'mailbox_info{version="0.9.0"}': 1,
        "mailbox_worker_enabled": 1,
        "mailbox_worker_interval_seconds": 300,
        "mailbox_worker_push": 1,
        "mailbox_worker_watched_accounts": 1,
        "mailbox_worker_last_round_timestamp_seconds": SECONDS,
        'mailbox_accounts{status="connected"}': 1,
        'mailbox_accounts{status="needs_reauth"}': 1,
        'mailbox_accounts{status="unreachable"}': 0,
        "mailbox_accounts_attention": 1,
        f'mailbox_account_status{{{imap},status="connected"}}': 1,
        f'mailbox_account_status{{{gmail},status="needs_reauth"}}': 1,
        f"mailbox_account_attention{{{imap}}}": 0,
        f"mailbox_account_attention{{{gmail}}}": 1,
        f"mailbox_account_synced{{{imap}}}": 1,
        f"mailbox_account_synced{{{gmail}}}": 1,
        f"mailbox_account_last_sync_timestamp_seconds{{{imap}}}": SECONDS,
        f"mailbox_account_sync_passes_total{{{imap}}}": 3,
        f"mailbox_account_sync_passes_total{{{gmail}}}": 1,
        "mailbox_webhooks": 2,
        "mailbox_webhooks_failing": 1,
    } | {name: value for name, value in found.items() if name.startswith("process_")}


def test_without_a_worker_only_that_it_is_off() -> None:
    found = lines(figures(worker=None))
    assert found["mailbox_worker_enabled"] == 0
    worker = [n for n in found if n.startswith("mailbox_worker_")]
    assert worker == ["mailbox_worker_enabled"]


def test_a_point_in_time_that_does_not_exist_is_no_series() -> None:
    before = WorkerState(
        interval=300, push=False, last_pass_at=None, watching=frozenset(), watchers=1
    )
    fresh = AccountHealth(IMAP, SyncState(), synced=True, watching=False)
    found = lines(figures(fresh, worker=before))
    assert not any("timestamp" in name for name in found)
    passes = 'mailbox_account_sync_passes_total{account="acc_1",provider="imap"}'
    assert found[passes] == 0


def test_an_account_no_pass_is_for_counts_no_passes() -> None:
    idle = AccountHealth(IMAP, SyncState(), synced=False, watching=False)
    found = lines(figures(idle))
    assert not any(name.startswith("mailbox_account_sync_passes") for name in found)
    assert found['mailbox_account_synced{account="acc_1",provider="imap"}'] == 0


def test_no_address_name_or_error_goes_out() -> None:
    troubled = AccountHealth(
        IMAP,
        SyncState(last_error="Ladybird refused", last_error_at=AT),
        synced=False,
        watching=False,
        problem="Bumblebee missing",
    )
    text = exposition(figures(troubled), "0.9.0").decode()
    for secret in ("example.org", "first", "Tinkerbell", "Ladybird", "Bumblebee"):
        assert secret not in text


def test_a_status_no_account_has_counts_0() -> None:
    found = lines(figures())
    assert found['mailbox_accounts{status="unreachable"}'] == 0
    assert found["mailbox_accounts_attention"] == 0


def test_the_answer_is_the_text_format() -> None:
    assert CONTENT_TYPE.startswith("text/plain")
