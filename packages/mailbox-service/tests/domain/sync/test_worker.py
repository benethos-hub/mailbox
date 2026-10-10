"""The background worker: polls, watches over IDLE, leaves rejected accounts
alone, and starts and stops with the app."""

from __future__ import annotations

import logging
from dataclasses import replace

import anyio
import pytest
from fastapi.testclient import TestClient

from benethos_mailbox_service.assembly import Services, create_app
from benethos_mailbox_service.config import Settings
from benethos_mailbox_service.data.models import AccountStatus, ProviderType
from benethos_mailbox_service.domain.rights.access import Access
from benethos_mailbox_service.domain.sync import worker as worker_module
from benethos_mailbox_service.domain.sync.worker import SyncWorker
from benethos_mailbox_service.domain.system.status import StatusService
from benethos_mailbox_service.errors import (
    ForbiddenError,
    NotFoundError,
    ProviderAuthError,
)

from ...conftest import ADMIN
from ...imap_fake import FakeMailBox, make_message


def worker(imap_services: Services, **options: object) -> SyncWorker:
    async def no_sleep(seconds: float) -> None:
        return None

    return SyncWorker(
        imap_services.adapters,
        imap_services.sync,
        interval=300,
        sleep=no_sleep,
        **options,  # type: ignore[arg-type]
    )


def indexed(imap_services: Services, imap_account_id: str) -> dict[str, str]:
    return imap_services.index.folder_states(imap_account_id)


async def test_a_poll_syncs_mapped_accounts(
    imap_services: Services,
    imap_account_id: str,
) -> None:
    memory = await imap_services.accounts.create(
        ADMIN, ProviderType.MEMORY, "m@example.com"
    )
    await worker(imap_services).poll()
    assert set(indexed(imap_services, imap_account_id)) != set()
    assert indexed(imap_services, memory.id) == {}


async def test_a_rejected_account_is_left_alone(
    imap_services: Services,
    imap_account_id: str,
    imap_server: FakeMailBox,
) -> None:
    imap_server.password = "changed"
    with pytest.raises(ProviderAuthError):
        await imap_services.sync.sync_account(imap_account_id)
    assert imap_services.adapters.status(imap_account_id) is AccountStatus.NEEDS_REAUTH
    logins = [c for c in imap_server.calls if c[0] == "login"]
    await worker(imap_services).poll()
    assert [c for c in imap_server.calls if c[0] == "login"] == logins


async def test_a_failing_account_does_not_stop_the_round(
    imap_services: Services,
    imap_account_id: str,
    imap_server: FakeMailBox,
    caplog: pytest.LogCaptureFixture,
) -> None:
    imap_server.failures = [OSError("gone")] * 3
    memory = await imap_services.accounts.create(
        ADMIN, ProviderType.MEMORY, "m@example.com"
    )
    with caplog.at_level(logging.WARNING):
        await worker(imap_services).poll()
    assert (
        f"the worker could not sync me@example.com ({imap_account_id})" in caplog.text
    )
    assert "secret" not in caplog.text
    assert memory.id  # the round went on


async def test_a_change_reported_over_idle_is_synced(
    imap_services: Services,
    imap_account_id: str,
    imap_server: FakeMailBox,
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    monkeypatch.setattr(worker_module, "IDLE_RENEW", 0.05)
    await imap_services.sync.sync_account(imap_account_id)
    before = indexed(imap_services, imap_account_id)
    imap_server.add("INBOX", 10, make_message("Arrived"))
    imap_server.idle_script = [[(5, b"EXISTS")]]
    with anyio.move_on_after(0.5):
        await worker(imap_services).watch(imap_account_id)
    assert indexed(imap_services, imap_account_id) != before
    assert ("idle", "INBOX") in imap_server.calls


async def test_past_the_cap_an_account_is_polled_only(
    imap_services: Services,
    imap_account_id: str,
    caplog: pytest.LogCaptureFixture,
) -> None:
    background = worker(imap_services, watchers=0)
    started: list[str] = []

    class Recorder:
        def start_soon(self, function: object, account: str) -> None:
            started.append(account)

    with caplog.at_level(logging.INFO):
        await background.poll(Recorder())  # type: ignore[arg-type]
        await background.poll(Recorder())  # type: ignore[arg-type]
    assert started == []
    assert background.state().watching == frozenset()
    assert background.state().watchers == 0
    # Said once, not every round.
    assert caplog.text.count("only: all 0 watchers are in use") == 1


def test_the_cap_comes_from_the_settings() -> None:
    from benethos_mailbox_service.assembly import build_services

    settings = Settings(storage="memory", sync_interval=300, sync_watchers=3)
    services = build_services(settings)
    assert services.worker is not None
    assert services.worker.state().watchers == 3


async def test_a_deleted_account_leaves_nothing_in_the_worker() -> None:
    """What the worker notes of an account goes with it, so its sets do
    not grow with every account deleted."""
    from benethos_mailbox_service.assembly import build_services

    services = build_services(Settings(storage="memory", sync_interval=300))
    background = services.worker
    assert background is not None
    account = await services.accounts.create(
        ADMIN, ProviderType.MEMORY, "m@example.com"
    )
    background._no_push.add(account.id)
    background._postponed.add(account.id)
    await services.accounts.delete(ADMIN, account.id)
    assert account.id not in background._no_push
    assert account.id not in background._postponed


async def test_without_idle_only_polling(
    imap_services: Services,
    imap_account_id: str,
    imap_server: FakeMailBox,
) -> None:
    imap_server.announced = ["IMAP4REV1"]
    background = worker(imap_services)
    await background.watch(imap_account_id)  # ends by itself
    started: list[str] = []

    class Recorder:
        def start_soon(self, function: object, account: str) -> None:
            started.append(account)

    await background.poll(Recorder())  # type: ignore[arg-type]
    assert started == []


async def test_idle_can_be_switched_off(
    imap_services: Services,
    imap_account_id: str,
) -> None:
    started: list[str] = []

    class Recorder:
        def start_soon(self, function: object, account: str) -> None:
            started.append(account)

    await worker(imap_services, push=False).poll(Recorder())  # type: ignore[arg-type]
    assert started == []
    await worker(imap_services).poll(Recorder())  # type: ignore[arg-type]
    assert started == [imap_account_id]


def test_the_app_starts_and_stops_the_worker(
    imap_services: Services,
    imap_account_id: str,
    imap_server: FakeMailBox,
) -> None:
    settings = Settings(storage="memory", sync_idle=False)
    running = replace(
        imap_services,
        worker=SyncWorker(imap_services.adapters, imap_services.sync, interval=300),
    )
    with TestClient(create_app(settings, running)) as client:
        assert client.get("/health").status_code == 200
    # Stopping closed the adapter's connection.
    assert imap_server.calls[-1] == ("logout",)


def test_no_worker_when_the_interval_is_zero(
    imap_services: Services,
) -> None:
    assert imap_services.worker is None


async def test_a_deleted_account_ends_the_watcher_at_once(
    imap_services: Services,
    imap_account_id: str,
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    slept: list[float] = []

    async def note(seconds: float) -> None:
        slept.append(seconds)
        raise AssertionError("the watcher paused instead of ending")

    async def gone(*args: object) -> None:
        raise NotFoundError(f"account {imap_account_id} not found")

    monkeypatch.setattr(imap_services.adapters, "call", gone)
    w = SyncWorker(imap_services.adapters, imap_services.sync, interval=300, sleep=note)
    await w.watch(imap_account_id)
    assert slept == []


async def test_a_rejected_login_ends_the_watcher(
    imap_services: Services,
    imap_account_id: str,
    imap_server: FakeMailBox,
) -> None:
    imap_server.password = "changed"
    await worker(imap_services).watch(imap_account_id)  # ends by itself
    assert imap_services.adapters.status(imap_account_id) is AccountStatus.NEEDS_REAUTH


async def test_the_worker_and_the_sync_keep_their_state(
    imap_services: Services,
    imap_account_id: str,
    imap_server: FakeMailBox,
) -> None:
    before = worker(imap_services)
    assert before.state().last_pass_at is None
    assert imap_services.sync.state(imap_account_id).last_sync_at is None
    await before.poll()
    synced = imap_services.sync.state(imap_account_id)
    assert synced.last_sync_at is not None and synced.last_error is None
    assert before.state().last_pass_at is not None
    assert before.state().interval == 300

    # A new message makes the next pass search, and the search fails.
    imap_server.add("INBOX", 10, make_message("Arrived"))
    imap_server.failures = [OSError("gone")] * 3
    await before.poll()
    failed = imap_services.sync.state(imap_account_id)
    assert failed.last_sync_at == synced.last_sync_at
    assert failed.last_error is not None and failed.last_error_at is not None


async def test_the_status_names_what_needs_attention(
    imap_services: Services,
    imap_account_id: str,
    imap_server: FakeMailBox,
) -> None:
    status = StatusService(
        imap_services.accounts,
        imap_services.sync,
        worker(imap_services),
        imap_services.webhooks,
    )
    assert [h.account.id for h in status.status(ADMIN).accounts] == [imap_account_id]
    assert status.status(ADMIN).attention == []
    imap_server.password = "changed"
    with pytest.raises(ProviderAuthError):
        await imap_services.sync.sync_account(imap_account_id)
    [health] = status.status(ADMIN).attention
    assert health.account.status is AccountStatus.NEEDS_REAUTH
    assert health.sync.last_error is not None and health.synced

    nobody = Access("usr_n", "nobody", [])
    assert not nobody.sees_status()
    with pytest.raises(ForbiddenError):
        status.status(nobody)


async def test_a_bug_in_one_account_does_not_stop_the_round(
    imap_services: Services,
    imap_account_id: str,
    monkeypatch: pytest.MonkeyPatch,
    caplog: pytest.LogCaptureFixture,
) -> None:
    memory = await imap_services.accounts.create(
        ADMIN, ProviderType.MEMORY, "m@example.com"
    )
    synced: list[str] = []

    async def sync_account(account: str) -> None:
        if account == imap_account_id:
            raise KeyError("a bug")
        synced.append(account)

    monkeypatch.setattr(imap_services.sync, "watched", lambda account: True)
    monkeypatch.setattr(imap_services.sync, "sync_account", sync_account)
    await worker(imap_services, push=False).poll()
    assert synced == [memory.id]
    assert (
        f"the worker could not sync me@example.com ({imap_account_id})" in caplog.text
    )
    assert "KeyError" in caplog.text


async def test_a_bug_while_watching_pauses_and_tries_again(
    imap_services: Services,
    imap_account_id: str,
    monkeypatch: pytest.MonkeyPatch,
    caplog: pytest.LogCaptureFixture,
) -> None:
    slept: list[float] = []

    async def note(seconds: float) -> None:
        slept.append(seconds)
        monkeypatch.setattr(imap_services.sync, "watched", lambda account: False)

    async def broken(*args: object) -> None:
        raise KeyError("a bug")

    monkeypatch.setattr(imap_services.sync, "watched", lambda account: True)
    monkeypatch.setattr(imap_services.adapters, "call", broken)
    await SyncWorker(
        imap_services.adapters, imap_services.sync, interval=300, sleep=note
    ).watch(imap_account_id)
    assert len(slept) == 1
    assert f"could not watch me@example.com ({imap_account_id})" in caplog.text


async def test_a_failed_round_does_not_end_the_worker(
    imap_services: Services,
    monkeypatch: pytest.MonkeyPatch,
    caplog: pytest.LogCaptureFixture,
) -> None:
    rounds: list[int] = []

    async def poll(watchers: object = None) -> None:
        rounds.append(1)
        raise RuntimeError("the index is gone")

    with anyio.CancelScope() as scope:

        async def sleep(seconds: float) -> None:
            if len(rounds) == 2:
                scope.cancel()
            await anyio.sleep(0)

        background = SyncWorker(
            imap_services.adapters, imap_services.sync, interval=300, sleep=sleep
        )
        monkeypatch.setattr(background, "poll", poll)
        await background.run()
    assert len(rounds) == 2
    assert "the worker could not finish a round" in caplog.text
