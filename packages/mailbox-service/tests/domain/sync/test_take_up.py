"""The worker takes an account up at once when it is connected, changed or
verified, not at its next round: a mail that arrives right after is in the
change feed, and a watcher waits for the server's push."""

from __future__ import annotations

from collections.abc import Callable

import anyio
import pytest
from pydantic import SecretStr

from benethos_mailbox_service.assembly import Services
from benethos_mailbox_service.data.models import AccountStatus, ProviderType
from benethos_mailbox_service.domain.sync.worker import SyncWorker

from ...conftest import ADMIN
from ...imap_fake import make_message
from ...jmap_fake import HOST, PASSWORD, USER, FakeJmap
from .test_jmap_sync import recorded, server, services_for

__all__ = ["server"]  # fixtures

# The tests switch the worker off unless asked.
WITH_WORKER = {"sync_interval": 300}


@pytest.fixture
def taken(monkeypatch: pytest.MonkeyPatch) -> list[str]:
    """What the worker is asked to take up, instead of doing it."""
    seen: list[str] = []
    monkeypatch.setattr(
        SyncWorker, "take_up", lambda self, account_id: seen.append(account_id)
    )
    return seen


@pytest.fixture
def services(
    taken: list[str], server: FakeJmap, monkeypatch: pytest.MonkeyPatch
) -> Services:
    return services_for(server, monkeypatch, **WITH_WORKER)


async def connect(services: Services) -> str:
    account = await services.accounts.create(
        ADMIN,
        ProviderType.JMAP,
        USER,
        settings={"host": HOST},
        credentials={"password": SecretStr(PASSWORD)},
    )
    return account.id


async def until(found: Callable[[], bool]) -> None:
    with anyio.fail_after(5):
        while not found():
            await anyio.sleep(0.01)


# --- what asks for it -----------------------------------------------------------------


async def test_connecting_changing_and_verifying_take_it_up(
    services: Services, taken: list[str]
) -> None:
    account_id = await connect(services)
    assert taken == [account_id]
    await services.accounts.update(ADMIN, account_id, display_name="Me", rename=True)
    assert taken == [account_id], "a new name changes nothing for the sync"
    await services.accounts.update(
        ADMIN, account_id, display_name=None, rename=False, settings={"port": 443}
    )
    await services.accounts.update(
        ADMIN,
        account_id,
        display_name=None,
        rename=False,
        credentials={"password": SecretStr(PASSWORD)},
    )
    await services.accounts.verify(ADMIN, account_id)
    assert taken == [account_id] * 4


async def test_without_a_worker_nothing_is_taken_up(
    server: FakeJmap, monkeypatch: pytest.MonkeyPatch
) -> None:
    services = services_for(server, monkeypatch, sync_interval=0)
    assert services.worker is None
    await connect(services)


def test_before_the_worker_runs_take_up_does_nothing(
    server: FakeJmap, monkeypatch: pytest.MonkeyPatch
) -> None:
    services = services_for(server, monkeypatch, **WITH_WORKER)
    assert services.worker is not None
    services.worker.take_up("acc_unknown")


# --- the running worker ---------------------------------------------------------------


@pytest.fixture
def running(server: FakeJmap, monkeypatch: pytest.MonkeyPatch) -> Services:
    # The event source stays open and quiet: watchers wait.
    server.hold = True
    return services_for(server, monkeypatch, **WITH_WORKER)


async def test_a_new_account_is_synced_and_watched_at_once(
    running: Services, server: FakeJmap
) -> None:
    worker = running.worker
    assert worker is not None
    async with anyio.create_task_group() as group:
        group.start_soon(worker.run)
        await until(lambda: worker.state().last_pass_at is not None)
        account_id = await connect(running)
        await until(
            lambda: (
                running.sync.state(account_id).last_sync_at is not None
                and account_id in worker.state().watching
            )
        )
        # Arrived after the first sync: the change feed names it.
        new = server.add_email(make_message("Right after"))
        await running.sync.sync_account(account_id)
        group.cancel_scope.cancel()
    assert ("message.created", new, "inbox") in recorded(running, account_id)


async def test_a_verified_account_is_watched_again(
    running: Services, server: FakeJmap
) -> None:
    worker = running.worker
    assert worker is not None
    account_id = await connect(running)
    running.adapters.set_status(account_id, AccountStatus.NEEDS_REAUTH)
    async with anyio.create_task_group() as group:
        group.start_soon(worker.run)
        await until(lambda: worker.state().last_pass_at is not None)
        assert account_id not in worker.state().watching
        await running.accounts.verify(ADMIN, account_id)
        await until(lambda: account_id in worker.state().watching)
        group.cancel_scope.cancel()


async def test_a_server_that_learnt_to_push_is_watched(
    running: Services, server: FakeJmap
) -> None:
    worker = running.worker
    assert worker is not None
    server.event_source = False
    account_id = await connect(running)
    async with anyio.create_task_group() as group:
        group.start_soon(worker.run)
        await until(lambda: worker.state().last_pass_at is not None)
        # The watcher found no event source and gave up.
        await until(lambda: account_id not in worker.state().watching)
        server.event_source = True
        await running.accounts.verify(ADMIN, account_id)
        await until(lambda: account_id in worker.state().watching)
        group.cancel_scope.cancel()
