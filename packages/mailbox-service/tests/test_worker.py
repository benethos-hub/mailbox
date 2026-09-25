"""The background worker: polls, watches over IDLE, leaves rejected accounts
alone, and starts and stops with the app."""

from __future__ import annotations

import logging

import anyio
import pytest
from fastapi.testclient import TestClient
from pydantic import SecretStr

from benethos_mailbox_service.config import Settings
from benethos_mailbox_service.data.models import AccountStatus, ProviderType
from benethos_mailbox_service.domain import worker as worker_module
from benethos_mailbox_service.domain.worker import SyncWorker
from benethos_mailbox_service.errors import ProviderAuthError
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
    return services.sync._index.folder_states(account_id)


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
    settings = Settings(storage="memory", api_key=SecretStr("k"), sync_idle=False)
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


async def test_a_rejected_login_ends_the_watcher(
    services: Services,  # noqa: F811
    account_id: str,  # noqa: F811
    server: FakeMailBox,  # noqa: F811
) -> None:
    server.password = "changed"
    await worker(services).watch(account_id)  # ends by itself
    assert services.adapters.status(account_id) is AccountStatus.NEEDS_REAUTH
