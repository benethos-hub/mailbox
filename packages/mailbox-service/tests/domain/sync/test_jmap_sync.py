"""A JMAP account through the real services and its adapter against a fake
server: the sync asks what changed since a state, the change feed reports
it, a push wakes the worker, and the API serves the account as any other."""

from __future__ import annotations

import json

import pytest
from fastapi.testclient import TestClient
from pydantic import SecretStr

from benethos_mailbox_service.assembly import Services, create_app
from benethos_mailbox_service.config import Settings
from benethos_mailbox_service.data.models import ProviderType

from ...conftest import admin_bearer, create_account
from ...imap_fake import make_message
from ...jmap_fake import HOST, TOKEN, USER, FakeJmap


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
    jmap_services: Services, jmap_account_id: str, jmap_server: FakeJmap
) -> None:
    pair = jmap_server.requests[-1].headers["authorization"]
    assert pair.startswith("Basic ")
    assert jmap_services.sync.watched(jmap_account_id)
    assert not jmap_services.sync.mapped(jmap_account_id)


async def test_the_sync_reports_what_changed(
    jmap_services: Services, jmap_account_id: str, jmap_server: FakeJmap
) -> None:
    await jmap_services.sync.sync_account(jmap_account_id)
    assert recorded(jmap_services, jmap_account_id) == []
    first, second = list(jmap_server.emails)
    new = jmap_server.add_email(make_message("New"))
    jmap_server.other_client_changes(first, mailboxIds={"trash": True})
    jmap_server.other_client_deletes(second)
    await jmap_services.sync.sync_account(jmap_account_id)
    assert sorted(recorded(jmap_services, jmap_account_id)) == sorted(
        [
            ("message.created", new, "inbox"),
            ("message.updated", first, "trash"),
            # JMAP does not say where a deleted message was.
            ("message.deleted", second, None),
        ]
    )


async def test_a_sync_without_changes_asks_once(
    jmap_services: Services, jmap_account_id: str, jmap_server: FakeJmap
) -> None:
    await jmap_services.sync.sync_account(jmap_account_id)
    jmap_server.calls.clear()
    await jmap_services.sync.sync_account(jmap_account_id)
    assert jmap_server.calls.count("Email/changes") == 1
    assert recorded(jmap_services, jmap_account_id) == []


async def test_a_push_wakes_the_sync(
    jmap_services: Services, jmap_account_id: str, jmap_server: FakeJmap
) -> None:
    await jmap_services.sync.sync_account(jmap_account_id)
    new = jmap_server.add_email(make_message("Pushed"))
    # The state the server reports next, past the one the wait starts from.
    data = {"changed": {"acc1": {"Email": "s-next"}}}
    jmap_server.events = ["event: state", f"data: {json.dumps(data)}", ""]
    changed = await jmap_services.adapters.call(
        jmap_account_id, lambda p: p.wait_for_change(5)
    )
    assert changed
    await jmap_services.sync.sync_account(jmap_account_id)
    assert ("message.created", new, "inbox") in recorded(jmap_services, jmap_account_id)


# --- through the API ------------------------------------------------------------------


def test_the_account_names_its_capabilities(
    client: TestClient, jmap_account_id: str
) -> None:
    account = client.get(f"/v1/accounts/{jmap_account_id}").json()
    assert account["provider"] == "jmap"
    assert account["settings"] == {"host": HOST, "username": USER}
    assert {"send", "drafts", "flags", "folders", "search", "push"} <= set(
        account["capabilities"]
    )
    assert [c["field"] for c in account["credentials"]] == ["password"]


def test_mail_through_the_api(
    client: TestClient, jmap_account_id: str, jmap_server: FakeJmap
) -> None:
    base = f"/v1/accounts/{jmap_account_id}"
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
    assert jmap_server.emails[message_id]["mailboxIds"] == {"trash": True}
    sent = client.post(
        f"{base}/send",
        json={"to": [{"email": "you@example.org"}], "subject": "Hi", "text": "Hello"},
    )
    assert sent.status_code == 200, sent.text
    [submission] = jmap_server.submissions
    assert submission["envelope"]["rcptTo"] == [{"email": "you@example.org"}]
    draft = client.post(
        f"{base}/drafts", json={"to": [{"email": "you@example.org"}], "subject": "D"}
    )
    assert draft.status_code == 201, draft.text


def test_a_token_account(jmap_services: Services, jmap_server: FakeJmap) -> None:
    account = create_account(
        jmap_services.accounts,
        ProviderType.JMAP,
        "other@example.com",
        settings={"host": HOST, "auth": "token"},
        credentials={"token": SecretStr(TOKEN)},
    )
    assert jmap_server.requests[-1].headers["authorization"] == f"Bearer {TOKEN}"
    assert [c.field for c in account.credentials] == ["token"]


def test_a_replaced_draft_answers_with_its_new_id(
    client: TestClient, jmap_account_id: str
) -> None:
    base = f"/v1/accounts/{jmap_account_id}/drafts"
    made = client.post(base, json={"subject": "Plan", "text": "first"}).json()
    replaced = client.put(
        f"{base}/{made['id']}", json={"subject": "Plan", "text": "second"}
    )
    assert replaced.status_code == 200, replaced.text
    new = replaced.json()["id"]
    assert new != made["id"]
    gone = client.get(f"/v1/accounts/{jmap_account_id}/messages/{made['id']}")
    assert gone.status_code == 404
    assert [d["id"] for d in client.get(base).json()["items"]] == [new]
