"""The background worker: polls, watches over IDLE, leaves rejected accounts
alone, and starts and stops with the app."""

from __future__ import annotations

import logging

import anyio
import pytest
from fastapi.testclient import TestClient

from benethos_mailbox_service.config import Settings
from benethos_mailbox_service.data.models import AccountStatus, ProviderType
from benethos_mailbox_service.domain import worker as worker_module
from benethos_mailbox_service.domain.access import Access
from benethos_mailbox_service.domain.status import StatusService
from benethos_mailbox_service.domain.worker import SyncWorker
from benethos_mailbox_service.errors import (
    ForbiddenError,
    NotFoundError,
    ProviderAuthError,
)
from benethos_mailbox_service.main import Services, create_app

from .conftest import ADMIN
from .imap_fake import FakeMailBox, make_message
from .test_sync import account_id, server, services  # noqa: F401 - fixtures


def worker(services: Services, **options: object) -> SyncWorker:  # noqa: F811
    async def no_sleep(seconds: float) -> None:
        return None

    return SyncWorker(
        services.adapters,
        services.sync,
        interval=300,
        sleep=no_sleep,
        **options,  # type: ignore[arg-type]
    )


def indexed(services: Services, account_id: str) -> dict[str, str]:  # noqa: F811
    return services.index.folder_states(account_id)


async def test_a_poll_syncs_mapped_accounts(
    services: Services,  # noqa: F811
    account_id: str,  # noqa: F811
) -> None:
    memory = await services.accounts.create(ADMIN, ProviderType.MEMORY, "m@example.com")
    await worker(services).poll()
    assert set(indexed(services, account_id)) != set()
    assert indexed(services, memory.id) == {}


async def test_a_rejected_account_is_left_alone(
    services: Services,  # noqa: F811
    account_id: str,  # noqa: F811
    server: FakeMailBox,  # noqa: F811
) -> None:
    server.password = "changed"
    with pytest.raises(ProviderAuthError):
        await services.sync.sync_account(account_id)
    assert services.adapters.status(account_id) is AccountStatus.NEEDS_REAUTH
    logins = [c for c in server.calls if c[0] == "login"]
    await worker(services).poll()
    assert [c for c in server.calls if c[0] == "login"] == logins


async def test_a_failing_account_does_not_stop_the_round(
    services: Services,  # noqa: F811
    account_id: str,  # noqa: F811
    server: FakeMailBox,  # noqa: F811
    caplog: pytest.LogCaptureFixture,
) -> None:
    server.failures = [OSError("gone")] * 3
    memory = await services.accounts.create(ADMIN, ProviderType.MEMORY, "m@example.com")
    with caplog.at_level(logging.WARNING):
        await worker(services).poll()
    assert f"sync of {account_id} failed" in caplog.text
    assert "secret" not in caplog.text
    assert memory.id  # the round went on


async def test_a_change_reported_over_idle_is_synced(
    services: Services,  # noqa: F811
    account_id: str,  # noqa: F811
    server: FakeMailBox,  # noqa: F811
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    monkeypatch.setattr(worker_module, "IDLE_RENEW", 0.05)
    await services.sync.sync_account(account_id)
    before = indexed(services, account_id)
    server.add("INBOX", 10, make_message("Arrived"))
    server.idle_script = [[(5, b"EXISTS")]]
    with anyio.move_on_after(0.5):
        await worker(services).watch(account_id)
    assert indexed(services, account_id) != before
    assert ("idle", "INBOX") in server.calls


async def test_without_idle_only_polling(
    services: Services,  # noqa: F811
    account_id: str,  # noqa: F811
    server: FakeMailBox,  # noqa: F811
) -> None:
    server.announced = ["IMAP4REV1"]
    background = worker(services)
    await background.watch(account_id)  # ends by itself
    started: list[str] = []

    class Recorder:
        def start_soon(self, function: object, account: str) -> None:
            started.append(account)

    await background.poll(Recorder())  # type: ignore[arg-type]
    assert started == []


async def test_idle_can_be_switched_off(
    services: Services,  # noqa: F811
    account_id: str,  # noqa: F811
) -> None:
    started: list[str] = []

    class Recorder:
        def start_soon(self, function: object, account: str) -> None:
            started.append(account)

    await worker(services, push=False).poll(Recorder())  # type: ignore[arg-type]
    assert started == []
    await worker(services).poll(Recorder())  # type: ignore[arg-type]
    assert started == [account_id]


def test_the_app_starts_and_stops_the_worker(
    services: Services,  # noqa: F811
    account_id: str,  # noqa: F811
    server: FakeMailBox,  # noqa: F811
) -> None:
    settings = Settings(storage="memory", sync_idle=False)
    running = Services(
        **{
            **services.__dict__,
            "worker": SyncWorker(services.adapters, services.sync, interval=300),
        }
    )
    with TestClient(create_app(settings, running)) as client:
        assert client.get("/health").status_code == 200
    # Stopping closed the adapter's connection.
    assert server.calls[-1] == ("logout",)


def test_no_worker_when_the_interval_is_zero(
    services: Services,  # noqa: F811
) -> None:
    assert services.worker is None


async def test_a_deleted_account_ends_the_watcher_at_once(
    services: Services,  # noqa: F811
    account_id: str,  # noqa: F811
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    slept: list[float] = []

    async def note(seconds: float) -> None:
        slept.append(seconds)
        raise AssertionError("the watcher paused instead of ending")

    async def gone(*args: object) -> None:
        raise NotFoundError(f"account {account_id} not found")

    monkeypatch.setattr(services.adapters, "call", gone)
    w = SyncWorker(services.adapters, services.sync, interval=300, sleep=note)
    await w.watch(account_id)
    assert slept == []


async def test_a_rejected_login_ends_the_watcher(
    services: Services,  # noqa: F811
    account_id: str,  # noqa: F811
    server: FakeMailBox,  # noqa: F811
) -> None:
    server.password = "changed"
    await worker(services).watch(account_id)  # ends by itself
    assert services.adapters.status(account_id) is AccountStatus.NEEDS_REAUTH


async def test_the_worker_and_the_sync_keep_their_state(
    services: Services,  # noqa: F811
    account_id: str,  # noqa: F811
    server: FakeMailBox,  # noqa: F811
) -> None:
    before = worker(services)
    assert before.state().last_pass_at is None
    assert services.sync.state(account_id).last_sync_at is None
    await before.poll()
    synced = services.sync.state(account_id)
    assert synced.last_sync_at is not None and synced.last_error is None
    assert before.state().last_pass_at is not None
    assert before.state().interval == 300

    # A new message makes the next pass search, and the search fails.
    server.add("INBOX", 10, make_message("Arrived"))
    server.failures = [OSError("gone")] * 3
    await before.poll()
    failed = services.sync.state(account_id)
    assert failed.last_sync_at == synced.last_sync_at
    assert failed.last_error is not None and failed.last_error_at is not None


async def test_the_status_names_what_needs_attention(
    services: Services,  # noqa: F811
    account_id: str,  # noqa: F811
    server: FakeMailBox,  # noqa: F811
) -> None:
    status = StatusService(
        services.accounts, services.sync, worker(services), services.webhooks
    )
    assert [h.account.id for h in status.status(ADMIN).accounts] == [account_id]
    assert status.status(ADMIN).attention == []
    server.password = "changed"
    with pytest.raises(ProviderAuthError):
        await services.sync.sync_account(account_id)
    [health] = status.status(ADMIN).attention
    assert health.account.status is AccountStatus.NEEDS_REAUTH
    assert health.sync.last_error is not None and health.synced

    nobody = Access("usr_n", "nobody", [])
    assert not status.may_see(nobody)
    with pytest.raises(ForbiddenError):
        status.status(nobody)


async def test_a_bug_in_one_account_does_not_stop_the_round(
    services: Services,  # noqa: F811
    account_id: str,  # noqa: F811
    monkeypatch: pytest.MonkeyPatch,
    caplog: pytest.LogCaptureFixture,
) -> None:
    memory = await services.accounts.create(ADMIN, ProviderType.MEMORY, "m@example.com")
    synced: list[str] = []

    async def sync_account(account: str) -> None:
        if account == account_id:
            raise KeyError("a bug")
        synced.append(account)

    monkeypatch.setattr(services.sync, "watched", lambda account: True)
    monkeypatch.setattr(services.sync, "sync_account", sync_account)
    await worker(services, push=False).poll()
    assert synced == [memory.id]
    assert f"sync of {account_id} failed" in caplog.text
    assert "KeyError" in caplog.text


async def test_a_bug_while_watching_pauses_and_tries_again(
    services: Services,  # noqa: F811
    account_id: str,  # noqa: F811
    monkeypatch: pytest.MonkeyPatch,
    caplog: pytest.LogCaptureFixture,
) -> None:
    slept: list[float] = []

    async def note(seconds: float) -> None:
        slept.append(seconds)
        monkeypatch.setattr(services.sync, "watched", lambda account: False)

    async def broken(*args: object) -> None:
        raise KeyError("a bug")

    monkeypatch.setattr(services.sync, "watched", lambda account: True)
    monkeypatch.setattr(services.adapters, "call", broken)
    await SyncWorker(services.adapters, services.sync, interval=300, sleep=note).watch(
        account_id
    )
    assert len(slept) == 1
    assert f"watching {account_id} failed" in caplog.text


async def test_a_failed_round_does_not_end_the_worker(
    services: Services,  # noqa: F811
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
            services.adapters, services.sync, interval=300, sleep=sleep
        )
        monkeypatch.setattr(background, "poll", poll)
        await background.run()
    assert len(rounds) == 2
    assert "a sync round failed" in caplog.text
