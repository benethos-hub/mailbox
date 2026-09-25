"""Webhooks: registering, listing and removing, their rights, and how the
secret is kept."""

from __future__ import annotations

from collections.abc import Iterator
from datetime import UTC, datetime
from pathlib import Path

import pytest
from fastapi.testclient import TestClient

from benethos_mailbox_service.data.models import Grant, ProviderType, Webhook
from benethos_mailbox_service.data.storage import (
    Database,
    Delivery,
    InMemoryWebhookRepository,
    Sealed,
    SqliteWebhookRepository,
    WebhookRecord,
    WebhookRepository,
)
from benethos_mailbox_service.domain.webhooks import sealed_label
from benethos_mailbox_service.errors import NotFoundError
from benethos_mailbox_service.main import Services

from .conftest import bearer_for, create_account

HOOK = {"url": "https://hooks.example.com/mail"}

# The vault needs its key before the services are built.
pytestmark = pytest.mark.usefixtures("master_key")


@pytest.fixture
def ready(services: Services) -> Services:
    """Services whose vault can seal a secret."""
    services.vault.initialize()
    return services


def test_create_answers_the_secret_once(
    client: TestClient, ready: Services, account_id: str
) -> None:
    created = client.post("/v1/webhooks", json=HOOK)
    assert created.status_code == 201, created.text
    body = created.json()
    assert body["secret"].startswith("whsec_")
    assert body["events"] == [
        "message.created",
        "message.updated",
        "message.deleted",
        "message.sent",
        "account.needs_reauth",
    ]
    assert body["accounts"] is None
    listed = client.get("/v1/webhooks").json()
    assert [w["id"] for w in listed] == [body["id"]]
    assert "secret" not in listed[0]


def test_the_secret_is_kept_sealed(client: TestClient, ready: Services) -> None:
    body = client.post("/v1/webhooks", json=HOOK).json()
    record = ready.webhooks._repository.get(body["id"])  # type: ignore[attr-defined]
    assert body["secret"].encode() not in record.secret.ciphertext
    opened = ready.vault.unseal(sealed_label(body["id"]), record.secret)
    assert opened.get_secret_value() == body["secret"]
    # Bound to its webhook: under another label it does not open.
    with pytest.raises(Exception, match="cannot be decrypted"):
        ready.vault.unseal(sealed_label("whk_other"), record.secret)


def test_a_new_webhook_hears_what_comes_from_now_on(
    client: TestClient, ready: Services, account_id: str
) -> None:
    client.patch(f"/v1/accounts/{account_id}/messages/m0", json={"unread": False})
    body = client.post("/v1/webhooks", json=HOOK).json()
    record = ready.webhooks._repository.get(body["id"])  # type: ignore[attr-defined]
    assert record.delivery.cursor == ready.changes.last() == 1


@pytest.mark.parametrize(
    "url",
    [
        "ftp://hooks.example.com/mail",
        "https:///no-host",
        "https://user:pass@hooks.example.com/mail",
        "not a url",
        "https://hooks.example.com:0/mail",
    ],
)
def test_a_url_that_will_not_do(client: TestClient, ready: Services, url: str) -> None:
    answer = client.post("/v1/webhooks", json={"url": url})
    assert answer.status_code == 400, url


def test_a_host_in_the_local_network_is_allowed(
    client: TestClient, ready: Services
) -> None:
    for url in ("http://192.168.1.10:5678/webhook", "http://homeassistant.local/x"):
        assert client.post("/v1/webhooks", json={"url": url}).status_code == 201


def test_only_known_events(client: TestClient, ready: Services) -> None:
    answer = client.post("/v1/webhooks", json={**HOOK, "events": ["mail.read"]})
    assert answer.status_code == 422
    assert client.post("/v1/webhooks", json={**HOOK, "events": []}).status_code == 422


def test_accounts_must_be_readable_by_the_creator(
    client: TestClient, ready: Services, account_id: str
) -> None:
    other = create_account(ready.accounts, ProviderType.MEMORY, "b@example.com")
    limited = TestClient(
        client.app,
        headers=bearer_for(
            ready,
            Grant(accounts=[account_id], allow=["mail.read", "webhooks.manage"]),
        ),
    )
    ok = limited.post("/v1/webhooks", json={**HOOK, "accounts": [account_id]})
    assert ok.status_code == 201
    hidden = limited.post("/v1/webhooks", json={**HOOK, "accounts": [other.id]})
    assert hidden.status_code == 404


def test_each_user_sees_and_removes_only_its_own(
    client: TestClient, ready: Services
) -> None:
    mine = client.post("/v1/webhooks", json=HOOK).json()["id"]
    someone = TestClient(
        client.app,
        headers=bearer_for(ready, Grant(accounts=["*"], allow=["webhooks.manage"])),
    )
    theirs = someone.post("/v1/webhooks", json=HOOK).json()["id"]
    assert [w["id"] for w in someone.get("/v1/webhooks").json()] == [theirs]
    assert someone.delete(f"/v1/webhooks/{mine}").status_code == 404
    assert someone.delete(f"/v1/webhooks/{theirs}").status_code == 204
    assert client.delete(f"/v1/webhooks/{mine}").status_code == 204
    assert client.get("/v1/webhooks").json() == []
    assert client.delete(f"/v1/webhooks/{mine}").status_code == 404


def test_webhooks_need_their_right(client: TestClient, ready: Services) -> None:
    reader = TestClient(
        client.app,
        headers=bearer_for(ready, Grant(accounts=["*"], allow=["mail.read"])),
    )
    for answer in (
        reader.get("/v1/webhooks"),
        reader.post("/v1/webhooks", json=HOOK),
        reader.delete("/v1/webhooks/whk_1"),
    ):
        assert answer.status_code == 403


# --- the store ----------------------------------------------------------------------

AT = datetime(2026, 9, 26, 12, 0, tzinfo=UTC)


@pytest.fixture(params=["memory", "sqlite"])
def store(
    request: pytest.FixtureRequest, tmp_path: Path
) -> Iterator[WebhookRepository]:
    if request.param == "memory":
        yield InMemoryWebhookRepository()
        return
    db = Database(tmp_path / "hooks.db")
    # The sealed secret names a data key that must exist.
    db.execute(
        "INSERT INTO keys (key_id, nonce, ciphertext) VALUES ('k1', x'00', x'00')"
    )
    yield SqliteWebhookRepository(db)
    db.close()


def record(n: int, accounts: list[str] | None = None) -> WebhookRecord:
    return WebhookRecord(
        webhook=Webhook(
            id=f"whk_{n}",
            url=f"https://h.example.com/{n}",
            events=["message.created"],
            accounts=accounts,
            user_id="usr_1",
            created_at=AT,
        ),
        secret=Sealed("k1", b"nonce", b"cipher"),
        delivery=Delivery(cursor=7),
    )


def test_the_store_keeps_a_webhook(store: WebhookRepository) -> None:
    store.add(record(1, accounts=["acc_1"]))
    store.add(record(2))
    assert store.get("whk_1") == record(1, accounts=["acc_1"])
    assert [r.webhook.id for r in store.list()] == ["whk_1", "whk_2"]
    store.delete("whk_1")
    with pytest.raises(NotFoundError):
        store.get("whk_1")
    with pytest.raises(NotFoundError):
        store.delete("whk_1")


def test_the_store_keeps_how_delivery_stands(store: WebhookRepository) -> None:
    store.add(record(1))
    later = Delivery(cursor=9, attempts=2, next_attempt_at=AT)
    store.update("whk_1", later, last_delivery_at=AT, last_error="503 from receiver")
    found = store.get("whk_1")
    assert found.delivery == later
    assert found.webhook.last_delivery_at == AT
    assert found.webhook.last_error == "503 from receiver"
    # Gone meanwhile: nothing happens.
    store.update("whk_9", later, last_delivery_at=None, last_error=None)
