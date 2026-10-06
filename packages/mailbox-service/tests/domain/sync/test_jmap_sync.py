"""A JMAP account through the real services and its adapter against a fake
server: the sync asks what changed since a state, the change feed reports
it, a push wakes the worker, and the API serves the account as any other."""

from __future__ import annotations

import json
from typing import Any

import httpx
import pytest
from fastapi.testclient import TestClient
from pydantic import SecretStr

from benethos_mailbox_service.config import Settings
from benethos_mailbox_service.data.models import ProviderType
from benethos_mailbox_service.data.protocols import ServerClient
from benethos_mailbox_service.data.providers import (
    CredentialReader,
    MailProvider,
    ProviderSettings,
)
from benethos_mailbox_service.data.providers.jmap import JmapProvider
from benethos_mailbox_service.data.providers.memory import MemoryProvider
from benethos_mailbox_service.data.secrets import cipher, encode_recovery
from benethos_mailbox_service.main import Services, build_services, create_app

from ...conftest import admin_bearer, create_account
from ...imap_fake import make_message
from ...jmap_fake import HOST, PASSWORD, TOKEN, USER, FakeJmap


@pytest.fixture
def server() -> FakeJmap:
    box = FakeJmap()
    for n in range(1, 3):
        box.add_email(make_message(f"Mail {n}"))
    return box


@pytest.fixture
def jmap_services(server: FakeJmap, monkeypatch: pytest.MonkeyPatch) -> Services:
    return services_for(server, monkeypatch)


def services_for(
    server: FakeJmap, monkeypatch: pytest.MonkeyPatch, **settings: Any
) -> Services:
    """The services, with JMAP accounts against ``server``. ``settings``
    change those of the tests."""
    monkeypatch.setenv("MAILBOX_SERVICE_MASTER_KEY", encode_recovery(cipher.new_key()))

    def factory(
        kind: ProviderType, settings: ProviderSettings, credentials: CredentialReader
    ) -> MailProvider:
        if kind is ProviderType.MEMORY:
            return MemoryProvider()
        return JmapProvider(
            settings,
            credentials,
            http=ServerClient(transport=httpx.MockTransport(server)),
        )

    services = build_services(
        Settings(storage="memory", **settings), provider_factory=factory
    )
    services.vault.initialize()
    return services


@pytest.fixture
def account_id(jmap_services: Services) -> str:
    return create_account(
        jmap_services.accounts,
        ProviderType.JMAP,
        USER,
        settings={"host": HOST},
        credentials={"password": SecretStr(PASSWORD)},
    ).id


@pytest.fixture
def client(jmap_services: Services) -> TestClient:
    app = create_app(Settings(storage="memory"), jmap_services)
    return TestClient(app, headers=admin_bearer(jmap_services))


def recorded(services: Services, account_id: str) -> list[tuple[str, str, str | None]]:
    return [
        (e.record.type, e.record.id, e.record.folder_id)
        for e in services.changes.after([account_id], 0, limit=1000)
    ]


async def test_the_sync_keeps_no_index_for_it(
    jmap_services: Services, account_id: str, server: FakeJmap
) -> None:
    pair = server.requests[-1].headers["authorization"]
    assert pair.startswith("Basic ")
    assert jmap_services.sync.watched(account_id)
    assert not jmap_services.sync.mapped(account_id)


async def test_the_sync_reports_what_changed(
    jmap_services: Services, account_id: str, server: FakeJmap
) -> None:
    await jmap_services.sync.sync_account(account_id)
    assert recorded(jmap_services, account_id) == []
    first, second = list(server.emails)
    new = server.add_email(make_message("New"))
    server.other_client_changes(first, mailboxIds={"trash": True})
    server.other_client_deletes(second)
    await jmap_services.sync.sync_account(account_id)
    assert sorted(recorded(jmap_services, account_id)) == sorted(
        [
            ("message.created", new, "inbox"),
            ("message.updated", first, "trash"),
            # JMAP does not say where a deleted message was.
            ("message.deleted", second, None),
        ]
    )


async def test_a_sync_without_changes_asks_once(
    jmap_services: Services, account_id: str, server: FakeJmap
) -> None:
    await jmap_services.sync.sync_account(account_id)
    server.calls.clear()
    await jmap_services.sync.sync_account(account_id)
    assert server.calls.count("Email/changes") == 1
    assert recorded(jmap_services, account_id) == []


async def test_a_push_wakes_the_sync(
    jmap_services: Services, account_id: str, server: FakeJmap
) -> None:
    await jmap_services.sync.sync_account(account_id)
    new = server.add_email(make_message("Pushed"))
    # The state the server reports next, past the one the wait starts from.
    data = {"changed": {"acc1": {"Email": "s-next"}}}
    server.events = ["event: state", f"data: {json.dumps(data)}", ""]
    changed = await jmap_services.adapters.call(
        account_id, lambda p: p.wait_for_change(5)
    )
    assert changed
    await jmap_services.sync.sync_account(account_id)
    assert ("message.created", new, "inbox") in recorded(jmap_services, account_id)


# --- through the API ------------------------------------------------------------------


def test_the_account_names_its_capabilities(
    client: TestClient, account_id: str
) -> None:
    account = client.get(f"/v1/accounts/{account_id}").json()
    assert account["provider"] == "jmap"
    assert account["settings"] == {"host": HOST, "username": USER}
    assert {"send", "drafts", "flags", "folders", "search", "push"} <= set(
        account["capabilities"]
    )
    assert [c["field"] for c in account["credentials"]] == ["password"]


def test_mail_through_the_api(
    client: TestClient, account_id: str, server: FakeJmap
) -> None:
    base = f"/v1/accounts/{account_id}"
    folders = {f["role"]: f["id"] for f in client.get(f"{base}/folders").json()}
    assert folders["inbox"] == "inbox"
    page = client.get(f"{base}/messages", params={"folder": "inbox"}).json()
    message_id = page["items"][0]["id"]
    starred = client.patch(f"{base}/messages/{message_id}", json={"starred": True})
    assert starred.status_code == 200 and starred.json()["starred"]
    moved = client.patch(
        f"{base}/messages/{message_id}", json={"folder_ids": ["archive"]}
    )
    assert moved.status_code == 404, moved.text  # no archive folder here
    trashed = client.delete(f"{base}/messages/{message_id}")
    assert trashed.status_code in (200, 204), trashed.text
    assert server.emails[message_id]["mailboxIds"] == {"trash": True}
    sent = client.post(
        f"{base}/send",
        json={"to": [{"email": "you@example.org"}], "subject": "Hi", "text": "Hello"},
    )
    assert sent.status_code == 200, sent.text
    [submission] = server.submissions
    assert submission["envelope"]["rcptTo"] == [{"email": "you@example.org"}]
    draft = client.post(
        f"{base}/drafts", json={"to": [{"email": "you@example.org"}], "subject": "D"}
    )
    assert draft.status_code == 201, draft.text


def test_a_token_account(jmap_services: Services, server: FakeJmap) -> None:
    account = create_account(
        jmap_services.accounts,
        ProviderType.JMAP,
        "other@example.com",
        settings={"host": HOST, "auth": "token"},
        credentials={"token": SecretStr(TOKEN)},
    )
    assert server.requests[-1].headers["authorization"] == f"Bearer {TOKEN}"
    assert [c.field for c in account.credentials] == ["token"]


def test_a_replaced_draft_answers_with_its_new_id(
    client: TestClient, account_id: str
) -> None:
    base = f"/v1/accounts/{account_id}/drafts"
    made = client.post(base, json={"subject": "Plan", "text": "first"}).json()
    replaced = client.put(
        f"{base}/{made['id']}", json={"subject": "Plan", "text": "second"}
    )
    assert replaced.status_code == 200, replaced.text
    new = replaced.json()["id"]
    assert new != made["id"]
    gone = client.get(f"/v1/accounts/{account_id}/messages/{made['id']}")
    assert gone.status_code == 404
    assert [d["id"] for d in client.get(base).json()["items"]] == [new]
