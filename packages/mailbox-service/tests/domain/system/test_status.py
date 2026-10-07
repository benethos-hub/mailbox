"""The status of the service through the API (`GET /v1/status`)."""

from __future__ import annotations

from datetime import UTC, datetime

from fastapi.testclient import TestClient

from benethos_mailbox_service.assembly import Services
from benethos_mailbox_service.data.models import Account, Grant, ProviderType
from benethos_mailbox_service.domain.sync import SyncState
from benethos_mailbox_service.domain.sync.worker import WorkerState
from benethos_mailbox_service.domain.system import AccountHealth, ServiceStatus
from benethos_mailbox_service.web.api.schemas import ServiceStatus as Answer

from ...conftest import bearer_for, create_account

AT = datetime(2026, 10, 6, 12, tzinfo=UTC)


def test_the_status_names_the_accounts_the_caller_may_see(
    app_client: TestClient, client: TestClient, services: Services, account_id: str
) -> None:
    other = create_account(services.accounts, ProviderType.MEMORY, "b@example.com").id
    answer = client.get("/v1/status")
    assert answer.status_code == 200, answer.text
    body = answer.json()
    assert body["worker"] is None  # switched off in the tests
    assert {a["id"] for a in body["accounts"]} == {account_id, other}
    [mine] = [a for a in body["accounts"] if a["id"] == account_id]
    assert mine["email"] == "me@example.com" and mine["status"] == "connected"
    assert (mine["last_error"], mine["attention"]) == (None, False)

    reader = bearer_for(services, Grant(accounts=[account_id], allow=["accounts.read"]))
    seen = app_client.get("/v1/status", headers=reader).json()["accounts"]
    assert [a["id"] for a in seen] == [account_id]
    for refused in (["mail.read"], ["list_accounts"]):
        headers = bearer_for(services, Grant(accounts=["*"], allow=refused))
        assert app_client.get("/v1/status", headers=headers).status_code == 403


def test_the_worker_names_how_many_it_watches_not_which() -> None:
    account = Account(id="acc_a", provider=ProviderType.IMAP, email="a@example.com")
    failed = SyncState(last_sync_at=AT, last_error="503 from server", last_error_at=AT)
    status = ServiceStatus(
        accounts=[AccountHealth(account, failed, synced=True, watching=True)],
        worker=WorkerState(
            interval=300,
            push=True,
            last_pass_at=AT,
            watching=frozenset({"acc_a", "acc_hidden"}),
            watchers=10,
        ),
        webhooks=[],
    )
    answer = Answer.of(status).model_dump(mode="json")
    assert answer["worker"] == {
        "interval": 300,
        "push": True,
        "last_pass_at": "2026-10-06T12:00:00Z",
        "watchers": 10,
        "watching": 2,
    }
    [health] = answer["accounts"]
    assert (health["watching"], health["attention"]) == (True, True)
    assert health["last_error"] == "503 from server"
    assert "acc_hidden" not in str(answer)
