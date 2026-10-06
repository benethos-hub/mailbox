"""A POP3 account through the real services and its adapter against a fake
server: the sync polls the unique ids and the change feed reports what
arrived and what left, and the API names what the account cannot do."""

from __future__ import annotations

import pytest
from fastapi.testclient import TestClient
from pydantic import SecretStr

from benethos_mailbox_service.config import Settings
from benethos_mailbox_service.data.models import ProviderType
from benethos_mailbox_service.data.protocols.pop3 import Pop3Session
from benethos_mailbox_service.data.providers import (
    CredentialReader,
    MailProvider,
    ProviderSettings,
)
from benethos_mailbox_service.data.providers.memory import MemoryProvider
from benethos_mailbox_service.data.providers.pop3 import Pop3Provider
from benethos_mailbox_service.data.secrets import cipher, encode_recovery
from benethos_mailbox_service.main import Services, build_services, create_app

from ...conftest import ADMIN, admin_bearer, create_account
from ...imap_fake import make_message
from ...pop3_fake import FakePop3Server


@pytest.fixture
def pop3_server() -> FakePop3Server:
    box = FakePop3Server()
    for n in range(1, 4):
        box.add(f"uid-{n}", make_message(f"Mail {n}"))
    return box


@pytest.fixture
def pop3_services(
    pop3_server: FakePop3Server, monkeypatch: pytest.MonkeyPatch
) -> Services:
    monkeypatch.setenv("MAILBOX_SERVICE_MASTER_KEY", encode_recovery(cipher.new_key()))

    def factory(
        kind: ProviderType, settings: ProviderSettings, credentials: CredentialReader
    ) -> MailProvider:
        if kind is ProviderType.MEMORY:
            return MemoryProvider()
        return Pop3Provider(
            settings,
            credentials,
            session_factory=lambda s: Pop3Session(s, connection_factory=pop3_server),
            sleep=lambda seconds: None,
        )

    services = build_services(Settings(storage="memory"), provider_factory=factory)
    services.vault.initialize()
    return services


@pytest.fixture
def pop3_account_id(pop3_services: Services) -> str:
    return create_account(
        pop3_services.accounts,
        ProviderType.POP3,
        "me@example.com",
        settings={"host": "pop.example.com"},
        credentials={"password": SecretStr("secret")},
    ).id


@pytest.fixture
def pop3_client(pop3_services: Services) -> TestClient:
    app = create_app(Settings(storage="memory"), pop3_services)
    return TestClient(app, headers=admin_bearer(pop3_services))


async def by_subject(services: Services, account_id: str) -> dict[str, str]:
    page = await services.mailbox.list_messages(
        ADMIN, account_id, folder_id=None, limit=50, cursor=None
    )
    return {m.subject or "": m.id for m in page.items}


def recorded(services: Services, account_id: str) -> list[tuple[str, str]]:
    return [
        (e.record.type, e.record.id)
        for e in services.changes.after([account_id], 0, limit=1000)
    ]


# --- the sync ---------------------------------------------------------------------


async def test_the_account_logs_in_with_its_address(
    pop3_services: Services, pop3_account_id: str, pop3_server: FakePop3Server
) -> None:
    assert ("user", "me@example.com") in pop3_server.calls


async def test_the_sync_polls_and_reports_what_arrived_and_left(
    pop3_services: Services, pop3_account_id: str, pop3_server: FakePop3Server
) -> None:
    assert pop3_services.sync.watched(pop3_account_id)
    await pop3_services.sync.sync_account(pop3_account_id)
    assert recorded(pop3_services, pop3_account_id) == []
    before = await by_subject(pop3_services, pop3_account_id)
    pop3_server.add("uid-4", make_message("New"))
    del pop3_server.messages["uid-1"]
    await pop3_services.sync.sync_account(pop3_account_id)
    new = (await by_subject(pop3_services, pop3_account_id))["New"]
    assert sorted(recorded(pop3_services, pop3_account_id)) == sorted(
        [("message.created", new), ("message.deleted", before["Mail 1"])]
    )


async def test_a_sync_without_changes_reads_no_headers(
    pop3_services: Services, pop3_account_id: str, pop3_server: FakePop3Server
) -> None:
    await pop3_services.sync.sync_account(pop3_account_id)
    pop3_server.calls.clear()
    await pop3_services.sync.sync_account(pop3_account_id)
    assert recorded(pop3_services, pop3_account_id) == []
    assert "top" not in [call[0] for call in pop3_server.calls]


async def test_ids_stay_the_same(
    pop3_services: Services, pop3_account_id: str, pop3_server: FakePop3Server
) -> None:
    first = await by_subject(pop3_services, pop3_account_id)
    await pop3_services.sync.sync_account(pop3_account_id)
    pop3_server.add("uid-4", make_message("New"))
    await pop3_services.sync.sync_account(pop3_account_id)
    again = await by_subject(pop3_services, pop3_account_id)
    assert {k: again[k] for k in first} == first


# --- through the API --------------------------------------------------------------


def test_the_account_names_its_capabilities(
    pop3_client: TestClient, pop3_account_id: str
) -> None:
    account = pop3_client.get(f"/v1/accounts/{pop3_account_id}").json()
    assert account["provider"] == "pop3" and account["capabilities"] == []
    [mine] = pop3_client.get("/v1/me").json()["accounts"]
    assert mine["capabilities"] == []


def test_what_pop3_cannot_do_answers_501(
    pop3_client: TestClient, pop3_account_id: str
) -> None:
    base = f"/v1/accounts/{pop3_account_id}"
    [folder] = pop3_client.get(f"{base}/folders").json()
    assert folder["role"] == "inbox"
    page = pop3_client.get(f"{base}/messages").json()
    message_id = page["items"][0]["id"]
    refused = [
        pop3_client.patch(f"{base}/messages/{message_id}", json={"starred": True}),
        pop3_client.delete(f"{base}/messages/{message_id}"),
        pop3_client.post(f"{base}/folders", json={"name": "Archive"}),
        pop3_client.get(f"{base}/messages", params={"unread": "true"}),
        pop3_client.get(f"{base}/drafts"),
    ]
    for answer in refused:
        assert answer.status_code == 501, answer.text
        assert answer.json()["error"]["code"] == "not_supported"
    gone = pop3_client.delete(
        f"{base}/messages/{message_id}", params={"permanent": "true"}
    )
    assert gone.status_code in (200, 204), gone.text
    after = pop3_client.get(f"{base}/messages").json()
    assert message_id not in [m["id"] for m in after["items"]]
