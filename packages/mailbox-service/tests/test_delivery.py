"""Posting events to webhooks: what is posted, signed and repeated, and
where a post may go."""

from __future__ import annotations

import hashlib
import hmac
import json
from datetime import UTC, datetime, timedelta
from typing import Any

import httpx
import pytest
from fastapi.testclient import TestClient

from benethos_mailbox_service.data.http import WebhookPoster, is_receiver_address
from benethos_mailbox_service.data.models import Grant, ProviderType
from benethos_mailbox_service.domain.delivery import BATCH, Retries, signature
from benethos_mailbox_service.errors import ProviderError, ProviderUnavailableError
from benethos_mailbox_service.main import Services

from .conftest import ADMIN, bearer_for

pytestmark = pytest.mark.usefixtures("master_key")
URL = "https://hooks.example.com/mail"


class Receiver:
    """Stands in for the WebhookPoster: records each post, answers a status."""

    def __init__(self) -> None:
        self.posts: list[tuple[str, bytes, dict[str, str]]] = []
        self.status = 204
        self.failure: Exception | None = None

    async def post(self, url: str, body: bytes, headers: dict[str, str]) -> int:
        self.posts.append((url, body, dict(headers)))
        if self.failure is not None:
            raise self.failure
        return self.status

    def events(self, n: int = -1) -> list[dict[str, Any]]:
        events: list[dict[str, Any]] = json.loads(self.posts[n][1])["events"]
        return events


class Clock:
    def __init__(self) -> None:
        self.now = datetime(2026, 9, 26, 12, 0, tzinfo=UTC)

    def __call__(self) -> datetime:
        return self.now


@pytest.fixture
def receiver(services: Services, monkeypatch: pytest.MonkeyPatch) -> Receiver:
    services.vault.initialize()
    fake = Receiver()
    monkeypatch.setattr(services.deliveries, "_poster", fake)
    return fake


@pytest.fixture
def clock(services: Services, monkeypatch: pytest.MonkeyPatch) -> Clock:
    fixed = Clock()
    monkeypatch.setattr(services.deliveries, "_clock", fixed)
    return fixed


def mark_read(client: TestClient, account_id: str, message_id: str) -> None:
    answer = client.patch(
        f"/v1/accounts/{account_id}/messages/{message_id}", json={"unread": False}
    )
    assert answer.status_code == 200


def hook(client: TestClient, **fields: Any) -> dict[str, Any]:
    answer = client.post("/v1/webhooks", json={"url": URL, **fields})
    assert answer.status_code == 201, answer.text
    created: dict[str, Any] = answer.json()
    return created


def stored(services: Services, webhook_id: str) -> Any:
    return services.webhooks._repository.get(webhook_id)  # type: ignore[attr-defined]


async def test_a_signed_post_of_what_happened(
    client: TestClient, services: Services, account_id: str, receiver: Receiver
) -> None:
    created = hook(client)
    mark_read(client, account_id, "m0")
    await services.deliveries.deliver_due()
    [(url, body, headers)] = receiver.posts
    assert url == URL
    posted = json.loads(body)
    assert posted["webhook_id"] == created["id"]
    assert posted["more"] is False
    assert [(e["type"], e["id"], e["account_id"]) for e in posted["events"]] == [
        ("message.updated", "m0", account_id)
    ]
    # The receiver checks the signature with the secret it was given.
    stamp, digest = (
        part.split("=", 1)[1] for part in headers["X-Mailbox-Signature"].split(",")
    )
    expected = hmac.new(
        created["secret"].encode(), f"{stamp}.".encode() + body, hashlib.sha256
    ).hexdigest()
    assert hmac.compare_digest(digest, expected)
    assert headers["X-Mailbox-Webhook-Id"] == created["id"]
    # Taken: nothing twice, and it says so.
    await services.deliveries.deliver_due()
    assert len(receiver.posts) == 1
    listed = client.get("/v1/webhooks").json()[0]
    assert listed["last_delivery_at"] is not None
    assert listed["last_error"] is None


def test_the_signature_is_hmac_sha256_of_time_and_body() -> None:
    value = signature("whsec_x", 1790000000, b'{"a":1}')
    digest = hmac.new(b"whsec_x", b'1790000000.{"a":1}', hashlib.sha256).hexdigest()
    assert value == f"t=1790000000,v1={digest}"


async def test_nothing_happened_nothing_posted(
    client: TestClient, services: Services, account_id: str, receiver: Receiver
) -> None:
    hook(client)
    await services.deliveries.deliver_due()
    assert receiver.posts == []


async def test_only_the_events_asked_for(
    client: TestClient, services: Services, account_id: str, receiver: Receiver
) -> None:
    hook(client, events=["message.sent"])
    mark_read(client, account_id, "m0")
    client.post(
        f"/v1/accounts/{account_id}/send",
        json={"to": [{"email": "bob@example.com"}], "subject": "Hi", "text": "x"},
    )
    await services.deliveries.deliver_due()
    assert [e["type"] for e in receiver.events()] == ["message.sent"]


async def test_only_accounts_the_creator_may_read(
    client: TestClient, services: Services, account_id: str, receiver: Receiver
) -> None:
    other = await services.accounts.create(ADMIN, ProviderType.MEMORY, "b@example.com")
    limited = TestClient(
        client.app,
        headers=bearer_for(
            services,
            Grant(accounts=[account_id], allow=["mail.read", "webhooks.manage"]),
        ),
    )
    hook(limited)
    mark_read(client, other.id, "m1")
    mark_read(client, account_id, "m0")
    await services.deliveries.deliver_due()
    assert [e["account_id"] for e in receiver.events()] == [account_id]


async def test_a_creator_that_is_gone_hears_nothing(
    client: TestClient, services: Services, account_id: str, receiver: Receiver
) -> None:
    headers = bearer_for(
        services, Grant(accounts=["*"], allow=["mail.read", "webhooks.manage"])
    )
    limited = TestClient(client.app, headers=headers)
    hook(limited)
    [user] = [u for u in services.users.list_users(ADMIN) if u.name == "limited"]
    client.delete(f"/v1/users/{user.id}")
    mark_read(client, account_id, "m0")
    await services.deliveries.deliver_due()
    assert receiver.posts == []


async def test_a_failed_post_is_tried_again_later(
    client: TestClient,
    services: Services,
    account_id: str,
    receiver: Receiver,
    clock: Clock,
) -> None:
    created = hook(client)
    mark_read(client, account_id, "m0")
    receiver.status = 503
    await services.deliveries.deliver_due()
    record = stored(services, created["id"])
    assert record.delivery.attempts == 1
    assert record.delivery.next_attempt_at == clock.now + timedelta(seconds=30)
    assert record.webhook.last_error == "the receiver answered 503"
    # Not yet due: nothing is posted.
    await services.deliveries.deliver_due()
    assert len(receiver.posts) == 1
    clock.now += timedelta(seconds=31)
    receiver.status = 200
    await services.deliveries.deliver_due()
    assert len(receiver.posts) == 2
    assert receiver.events() == receiver.events(0)
    record = stored(services, created["id"])
    assert record.delivery.attempts == 0
    assert record.webhook.last_error is None


async def test_after_the_last_attempt_the_events_are_dropped(
    client: TestClient,
    services: Services,
    account_id: str,
    receiver: Receiver,
    clock: Clock,
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    monkeypatch.setattr(
        services.deliveries, "_retries", Retries(attempts=3, first_retry=10)
    )
    created = hook(client)
    mark_read(client, account_id, "m0")
    receiver.failure = ProviderUnavailableError("hooks.example.com is not reachable")
    pauses = []
    for _ in range(3):
        await services.deliveries.deliver_due()
        record = stored(services, created["id"])
        if record.delivery.next_attempt_at is not None:
            pauses.append(record.delivery.next_attempt_at - clock.now)
            clock.now = record.delivery.next_attempt_at
    assert pauses == [timedelta(seconds=10), timedelta(seconds=20)]
    record = stored(services, created["id"])
    assert record.delivery.attempts == 0
    assert record.webhook.last_error == (
        "hooks.example.com is not reachable. 1 events were dropped after 3 attempts"
    )
    # The next event is posted, the dropped one not again.
    receiver.failure = None
    mark_read(client, account_id, "m1")
    await services.deliveries.deliver_due()
    assert [e["id"] for e in receiver.events()] == ["m1"]


def test_the_pause_doubles_up_to_the_longest() -> None:
    retries = Retries(attempts=10, first_retry=30, longest_retry=100)
    assert [retries.pause(n).total_seconds() for n in (1, 2, 3, 4)] == [
        30,
        60,
        100,
        100,
    ]


async def test_many_events_go_in_batches(
    client: TestClient, services: Services, account_id: str, receiver: Receiver
) -> None:
    hook(client)
    services.changes.record(
        account_id, "message.updated", [f"m{i}" for i in range(150)]
    )
    await services.deliveries.deliver_due()
    assert [len(receiver.events(n)) for n in range(len(receiver.posts))] == [BATCH, 50]
    assert [json.loads(p[1])["more"] for p in receiver.posts] == [True, False]


async def test_events_purged_before_posting_are_noted(
    client: TestClient,
    services: Services,
    account_id: str,
    receiver: Receiver,
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    created = hook(client)
    mark_read(client, account_id, "m0")
    later = datetime.now(UTC) + timedelta(days=8)
    monkeypatch.setattr(services.changes, "_clock", lambda: later)
    services.changes.purge()
    await services.deliveries.deliver_due()
    assert receiver.posts == []
    record = stored(services, created["id"])
    assert record.webhook.last_error == "events were purged before they could be posted"


async def test_a_removed_webhook_is_not_posted_to(
    client: TestClient, services: Services, account_id: str, receiver: Receiver
) -> None:
    created = hook(client)
    mark_read(client, account_id, "m0")
    client.delete(f"/v1/webhooks/{created['id']}")
    await services.deliveries.deliver_due()
    assert receiver.posts == []


# --- where a post may go ------------------------------------------------------------


def poster(address: str, seen: list[httpx.Request], status: int = 204) -> WebhookPoster:
    async def resolve(host: str, port: int) -> list[str]:
        return [address]

    def answer(request: httpx.Request) -> httpx.Response:
        seen.append(request)
        return httpx.Response(status)

    return WebhookPoster(resolve=resolve, transport=httpx.MockTransport(answer))


async def test_a_post_goes_to_the_checked_address() -> None:
    seen: list[httpx.Request] = []
    status = await poster("192.168.1.10", seen).post(
        "http://n8n.home:5678/webhook/mail", b"{}", {"X-A": "1"}
    )
    assert status == 204
    [request] = seen
    assert request.url.host == "192.168.1.10"
    assert request.url.port == 5678
    assert request.headers["host"] == "n8n.home:5678"
    assert request.headers["x-a"] == "1"
    assert request.content == b"{}"


async def test_https_keeps_the_name_for_the_certificate() -> None:
    seen: list[httpx.Request] = []
    await poster("93.184.215.14", seen).post(URL, b"{}", {})
    assert seen[0].extensions["sni_hostname"] == "hooks.example.com"


async def test_a_redirect_is_not_followed() -> None:
    seen: list[httpx.Request] = []
    assert await poster("10.0.0.5", seen, status=302).post(URL, b"{}", {}) == 302
    assert len(seen) == 1


@pytest.mark.parametrize(
    "address", ["169.254.169.254", "fe80::1", "224.0.0.1", "0.0.0.0"]
)
async def test_addresses_no_receiver_has_are_refused(address: str) -> None:
    seen: list[httpx.Request] = []
    with pytest.raises(ProviderError, match="refused"):
        await poster(address, seen).post(URL, b"{}", {})
    assert seen == []


@pytest.mark.parametrize(
    ("address", "ok"),
    [
        ("10.0.0.5", True),
        ("127.0.0.1", True),
        ("::1", True),
        ("93.184.215.14", True),
        ("169.254.169.254", False),
        ("::ffff:169.254.169.254", False),
    ],
)
def test_receiver_addresses(address: str, ok: bool) -> None:
    assert is_receiver_address(address) is ok


async def test_a_host_that_does_not_resolve() -> None:
    async def nowhere(host: str, port: int) -> list[str]:
        return []

    with pytest.raises(ProviderUnavailableError, match="does not resolve"):
        await WebhookPoster(resolve=nowhere).post(URL, b"{}", {})
