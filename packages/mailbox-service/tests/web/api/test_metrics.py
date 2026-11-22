"""The figures of the service for Prometheus through the API
(`GET /v1/metrics`)."""

from __future__ import annotations

from datetime import UTC, datetime

import pytest
from fastapi.testclient import TestClient

from benethos_mailbox_service.assembly import Services, create_app
from benethos_mailbox_service.config import Settings
from benethos_mailbox_service.data.models import Grant, ProviderType
from benethos_mailbox_service.domain.sync import SyncState

from ...conftest import admin_bearer, bearer_for, create_account

AT = datetime(2026, 11, 22, 12, tzinfo=UTC)


@pytest.fixture
def on(services: Services) -> TestClient:
    """A client without credentials, of a service with its metrics on."""
    return TestClient(create_app(Settings(storage="memory", metrics=True), services))


def monitor(services: Services) -> dict[str, str]:
    return bearer_for(services, service=["metrics"])


def test_switched_off_the_route_is_not_found(services: Services) -> None:
    off = TestClient(create_app(Settings(storage="memory"), services))
    answer = off.get("/v1/metrics", headers=admin_bearer(services))
    assert answer.status_code == 404
    assert answer.json()["error"]["code"] == "not_found"


def test_without_a_token_nothing(on: TestClient, services: Services) -> None:
    monitor(services)  # a user exists, else the service answers 503
    assert on.get("/v1/metrics").status_code == 401


def test_a_right_on_every_account_is_not_enough(
    on: TestClient, services: Services
) -> None:
    reader = bearer_for(services, Grant(accounts=["*"], allow=["accounts.read"]))
    answer = on.get("/v1/metrics", headers=reader)
    assert answer.status_code == 403
    assert "missing right: get_metrics" in answer.json()["error"]["message"]


def test_the_monitor_sees_every_account_and_nothing_else(
    on: TestClient, services: Services, account_id: str
) -> None:
    other = create_account(services.accounts, ProviderType.MEMORY, "b@example.com")
    headers = monitor(services)
    answer = on.get("/v1/metrics", headers=headers)
    assert answer.status_code == 200, answer.text
    assert answer.headers["content-type"].startswith("text/plain")
    assert f'account="{account_id}"' in answer.text
    assert f'account="{other.id}"' in answer.text
    assert on.get("/v1/status", headers=headers).status_code == 403
    accounts = on.get("/v1/accounts", headers=headers)
    assert accounts.status_code == 200 and accounts.json()["items"] == []


def test_no_address_and_no_error_in_the_answer(
    on: TestClient,
    services: Services,
    account_id: str,
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    failed = SyncState(last_error="Ladybird refused", last_error_at=AT)
    monkeypatch.setattr(services.sync, "state", lambda _account_id: failed)
    text = on.get("/v1/metrics", headers=monitor(services)).text
    names = f'account="{account_id}",provider="memory"'
    assert f"mailbox_account_attention{{{names}}} 1.0" in text
    assert "Ladybird" not in text and "example.com" not in text


def test_a_deleted_account_has_no_series(
    client: TestClient, on: TestClient, services: Services, account_id: str
) -> None:
    headers = monitor(services)
    assert account_id in on.get("/v1/metrics", headers=headers).text
    assert client.delete(f"/v1/accounts/{account_id}").status_code == 204
    assert account_id not in on.get("/v1/metrics", headers=headers).text
