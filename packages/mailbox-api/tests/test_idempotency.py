"""Idempotency-Key on sending (CONCEPT 6.4)."""

from __future__ import annotations

from collections.abc import Iterator
from datetime import UTC, datetime, timedelta
from pathlib import Path

import anyio
import pytest
from fastapi.testclient import TestClient

from benethos_mailbox_api.data.models import Account, ProviderType, SendResult
from benethos_mailbox_api.data.providers.memory import MemoryProvider
from benethos_mailbox_api.data.storage import (
    Database,
    IdempotencyRepository,
    InMemoryIdempotencyRepository,
    SqliteAccountRepository,
    SqliteIdempotencyRepository,
    StoredResult,
)
from benethos_mailbox_api.domain.idempotency import Idempotency
from benethos_mailbox_api.errors import IdempotencyConflictError, ProviderError
from benethos_mailbox_api.main import Services

BODY = {"to": [{"email": "you@example.com"}], "subject": "Once", "text": "Hallo"}


def outbox(services: Services, account_id: str) -> list[object]:
    provider = services.accounts.provider(account_id)
    assert isinstance(provider, MemoryProvider)
    return list(provider.outbox)


# --- through the API ------------------------------------------------------


def test_a_retry_returns_the_first_result(
    client: TestClient, services: Services, account_id: str
) -> None:
    url = f"/v1/accounts/{account_id}/send"
    first = client.post(url, json=BODY, headers={"Idempotency-Key": "k1"})
    again = client.post(url, json=BODY, headers={"Idempotency-Key": "k1"})
    assert first.status_code == again.status_code == 200
    assert again.json() == first.json()
    assert len(outbox(services, account_id)) == 1


def test_the_same_key_with_another_message(
    client: TestClient, services: Services, account_id: str
) -> None:
    url = f"/v1/accounts/{account_id}/send"
    client.post(url, json=BODY, headers={"Idempotency-Key": "k1"})
    other = client.post(
        url, json={**BODY, "subject": "Other"}, headers={"Idempotency-Key": "k1"}
    )
    assert other.status_code == 409
    assert other.json()["error"]["code"] == "idempotency_conflict"
    assert len(outbox(services, account_id)) == 1


def test_without_a_key_every_request_sends(
    client: TestClient, services: Services, account_id: str
) -> None:
    url = f"/v1/accounts/{account_id}/send"
    client.post(url, json=BODY)
    client.post(url, json=BODY)
    assert len(outbox(services, account_id)) == 2


def test_an_empty_key_is_refused(client: TestClient, account_id: str) -> None:
    answer = client.post(
        f"/v1/accounts/{account_id}/send", json=BODY, headers={"Idempotency-Key": ""}
    )
    assert answer.status_code == 422


# --- the rules ------------------------------------------------------------


class Clock:
    def __init__(self) -> None:
        self.now = datetime(2026, 9, 24, 12, 0, tzinfo=UTC)

    def __call__(self) -> datetime:
        return self.now


RESULT = SendResult(message_id_header="<1@example.com>")


async def test_a_key_counts_for_24_hours() -> None:
    clock = Clock()
    idempotency = Idempotency(InMemoryIdempotencyRepository(), clock)
    calls = []

    async def action() -> SendResult:
        calls.append(1)
        return RESULT

    request = SendResult(message_id_header="request")
    await idempotency.run("acc", "k", "send_message", request, action, SendResult)
    clock.now += timedelta(hours=23)
    await idempotency.run("acc", "k", "send_message", request, action, SendResult)
    assert len(calls) == 1
    clock.now += timedelta(hours=2)
    await idempotency.run("acc", "k", "send_message", request, action, SendResult)
    assert len(calls) == 2


async def test_keys_are_per_account_and_operation() -> None:
    idempotency = Idempotency(InMemoryIdempotencyRepository())
    request = SendResult(message_id_header="request")

    async def action() -> SendResult:
        return RESULT

    await idempotency.run("acc_a", "k", "send_message", request, action, SendResult)
    await idempotency.run("acc_b", "k", "send_message", request, action, SendResult)
    with pytest.raises(IdempotencyConflictError):
        await idempotency.run("acc_a", "k", "send_draft", request, action, SendResult)


async def test_a_failure_is_not_stored() -> None:
    idempotency = Idempotency(InMemoryIdempotencyRepository())
    request = SendResult(message_id_header="request")
    attempts = []

    async def flaky() -> SendResult:
        attempts.append(1)
        if len(attempts) == 1:
            raise ProviderError("down")
        return RESULT

    with pytest.raises(ProviderError):
        await idempotency.run("acc", "k", "send_message", request, flaky, SendResult)
    result = await idempotency.run(
        "acc", "k", "send_message", request, flaky, SendResult
    )
    assert result == RESULT


async def test_a_retry_during_the_first_waits_for_it() -> None:
    idempotency = Idempotency(InMemoryIdempotencyRepository())
    request = SendResult(message_id_header="request")
    sends = []

    async def slow() -> SendResult:
        sends.append(1)
        await anyio.sleep(0.05)
        return RESULT

    results: list[SendResult] = []

    async def call() -> None:
        results.append(
            await idempotency.run("acc", "k", "send_message", request, slow, SendResult)
        )

    async with anyio.create_task_group() as group:
        group.start_soon(call)
        group.start_soon(call)
    assert len(sends) == 1
    assert results == [RESULT, RESULT]


# --- storage --------------------------------------------------------------


@pytest.fixture(params=["memory", "sqlite"])
def store(
    request: pytest.FixtureRequest, tmp_path: Path
) -> Iterator[IdempotencyRepository]:
    if request.param == "memory":
        yield InMemoryIdempotencyRepository()
        return
    db = Database(tmp_path / "idem.db")
    SqliteAccountRepository(db).add(
        Account(id="acc", provider=ProviderType.IMAP, email="a@example.com")
    )
    yield SqliteIdempotencyRepository(db)
    db.close()


def test_store_round_trip_and_purge(store: IdempotencyRepository) -> None:
    then = datetime(2026, 9, 24, 12, 0, tzinfo=UTC)
    stored = StoredResult("send_message", "hash", '{"a":1}', then)
    store.put("acc", "k", stored)
    assert store.get("acc", "k") == stored
    assert store.get("acc", "other") is None
    store.purge(then)
    assert store.get("acc", "k") == stored
    store.purge(then + timedelta(seconds=1))
    assert store.get("acc", "k") is None
