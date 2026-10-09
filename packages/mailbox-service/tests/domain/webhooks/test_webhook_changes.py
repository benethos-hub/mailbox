"""Webhooks changed after they were made: their URL, events and accounts,
and a new signing secret (CONCEPT 6.5)."""

from __future__ import annotations

from collections.abc import Iterator
from datetime import UTC, datetime
from pathlib import Path

import pytest
from fastapi.testclient import TestClient

from benethos_mailbox_service.assembly import Services
from benethos_mailbox_service.data.models import (
    ActivityFilter,
    Grant,
    ProviderType,
    Webhook,
)
from benethos_mailbox_service.data.storage import (
    Database,
    Delivery,
    InMemoryWebhookRepository,
    Sealed,
    SqliteWebhookRepository,
    WebhookRecord,
    WebhookRepository,
)
from benethos_mailbox_service.domain.webhooks.service import sealed_label

from ...conftest import ADMIN, bearer_for, create_account

HOOK = {"url": "https://hooks.example.com/mail"}
AT = datetime(2026, 10, 9, 12, tzinfo=UTC)

pytestmark = pytest.mark.usefixtures("master_key")


@pytest.fixture
def ready(services: Services) -> Services:
    services.vault.initialize()
    return services


def audited(services: Services, name: str) -> list[str]:
    found = services.audit.list_activity(
        ADMIN, limit=10, matching=ActivityFilter(activity=name)
    )
    return [record.detail for record in found.items]


# --- changing ---------------------------------------------------------------------


def test_a_field_left_out_stays_and_the_delivery_with_it(
    client: TestClient, ready: Services, account_id: str
) -> None:
    made = client.post(
        "/v1/webhooks",
        json={**HOOK, "events": ["message.created"], "accounts": [account_id]},
    ).json()
    before = ready.repositories.webhooks.get(made["id"])
    changed = client.patch(
        f"/v1/webhooks/{made['id']}", json={"url": "https://other.example.org/x"}
    )
    assert changed.status_code == 200, changed.text
    body = changed.json()
    assert body["url"] == "https://other.example.org/x"
    assert body["events"] == ["message.created"] and body["accounts"] == [account_id]
    after = ready.repositories.webhooks.get(made["id"])
    # Where its posts stand and its secret stay: nothing is lost or posted twice.
    assert after.delivery == before.delivery and after.secret == before.secret
    assert audited(ready, "webhooks.changed") == [
        f"changed the url of webhook {made['id']}, posting to other.example.org"
    ]


def test_accounts_null_is_every_account_and_a_list_needs_the_right(
    client: TestClient, ready: Services, account_id: str
) -> None:
    other = create_account(ready.accounts, ProviderType.MEMORY, "b@example.com")
    limited = TestClient(
        client.app,
        headers=bearer_for(
            ready,
            Grant(accounts=[account_id], allow=["mail.read"]),
            service=["webhooks.manage"],
        ),
    )
    made = limited.post("/v1/webhooks", json={**HOOK, "accounts": [account_id]})
    hook = made.json()["id"]
    every = limited.patch(f"/v1/webhooks/{hook}", json={"accounts": None})
    assert every.status_code == 200 and every.json()["accounts"] is None
    hidden = limited.patch(f"/v1/webhooks/{hook}", json={"accounts": [other.id]})
    assert hidden.status_code == 404
    assert limited.get(f"/v1/webhooks/{hook}").json()["accounts"] is None


@pytest.mark.parametrize(
    "change",
    [
        {"url": "ftp://hooks.example.com"},
        {"url": None},
        {"events": None},
        {"events": []},
        {"events": ["message.read"]},
    ],
)
def test_a_change_that_will_not_do(
    client: TestClient, ready: Services, change: dict[str, object]
) -> None:
    hook = client.post("/v1/webhooks", json=HOOK).json()["id"]
    refused = client.patch(f"/v1/webhooks/{hook}", json=change)
    assert refused.status_code in (400, 422), refused.text
    assert client.get(f"/v1/webhooks/{hook}").json()["url"] == HOOK["url"]


def test_nothing_changed_records_nothing(client: TestClient, ready: Services) -> None:
    hook = client.post("/v1/webhooks", json=HOOK).json()["id"]
    same = client.patch(f"/v1/webhooks/{hook}", json=HOOK)
    assert same.status_code == 200
    assert audited(ready, "webhooks.changed") == []


def test_only_its_owner_changes_a_webhook(client: TestClient, ready: Services) -> None:
    hook = client.post("/v1/webhooks", json=HOOK).json()["id"]
    someone = TestClient(
        client.app, headers=bearer_for(ready, service=["webhooks.manage"])
    )
    assert someone.patch(f"/v1/webhooks/{hook}", json=HOOK).status_code == 404
    assert someone.post(f"/v1/webhooks/{hook}/secret").status_code == 404
    reader = TestClient(client.app, headers=bearer_for(ready))
    assert reader.patch(f"/v1/webhooks/{hook}", json=HOOK).status_code == 403
    assert reader.post(f"/v1/webhooks/{hook}/secret").status_code == 403


# --- a new secret -----------------------------------------------------------------


def test_a_new_secret_is_shown_once_and_the_old_one_stops(
    client: TestClient, ready: Services
) -> None:
    made = client.post("/v1/webhooks", json=HOOK).json()
    renewed = client.post(f"/v1/webhooks/{made['id']}/secret")
    assert renewed.status_code == 200, renewed.text
    body = renewed.json()
    assert body["webhook_id"] == made["id"] and body["secret"].startswith("whsec_")
    assert body["secret"] != made["secret"]
    record = ready.repositories.webhooks.get(made["id"])
    opened = ready.vault.unseal(sealed_label(made["id"]), record.secret)
    assert opened.get_secret_value() == body["secret"]
    assert "secret" not in client.get(f"/v1/webhooks/{made['id']}").json()
    [said] = audited(ready, "webhooks.secret_renewed")
    assert made["id"] in said and body["secret"] not in said


# --- the store --------------------------------------------------------------------


@pytest.fixture(params=["memory", "sqlite"])
def store(
    request: pytest.FixtureRequest, tmp_path: Path
) -> Iterator[WebhookRepository]:
    if request.param == "memory":
        yield InMemoryWebhookRepository()
        return
    db = Database(tmp_path / "hooks.db")
    db.execute(
        "INSERT INTO keys (key_id, nonce, ciphertext) VALUES ('k1', x'00', x'00')"
    )
    yield SqliteWebhookRepository(db)
    db.close()


def test_the_store_changes_a_webhook_and_its_secret(store: WebhookRepository) -> None:
    store.add(
        WebhookRecord(
            webhook=Webhook(
                id="whk_1",
                url="https://h.example.com/1",
                events=["message.created"],
                accounts=["acc_1"],
                user_id="usr_1",
                created_at=AT,
            ),
            secret=Sealed("k1", b"nonce", b"cipher"),
            delivery=Delivery(cursor=7),
        )
    )
    store.change(
        "whk_1", url="https://h.example.com/2", events=["message.sent"], accounts=None
    )
    store.set_secret("whk_1", Sealed("k1", b"other", b"secret"))
    record = store.get("whk_1")
    assert record.webhook.url == "https://h.example.com/2"
    assert record.webhook.events == ["message.sent"] and record.webhook.accounts is None
    assert record.secret == Sealed("k1", b"other", b"secret")
    assert record.delivery == Delivery(cursor=7)
