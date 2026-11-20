"""No change puts a message into the drafts folder: the draft operations
take what lies there for a draft, and would delete it for good or send
it. A real draft still changes, goes and leaves the drafts folder."""

from __future__ import annotations

from collections.abc import Callable
from typing import Any

import pytest
from fastapi.testclient import TestClient
from pydantic import SecretStr

from benethos_mailbox_service.assembly import Services, build_services, create_app
from benethos_mailbox_service.config import Settings
from benethos_mailbox_service.data.models import Grant, ProviderType
from benethos_mailbox_service.data.protocols.imap import ImapSession
from benethos_mailbox_service.data.providers import (
    CredentialReader,
    ProviderSettings,
    Reads,
    Timing,
)
from benethos_mailbox_service.data.providers.imap import ImapProvider

from ...conftest import (
    admin_bearer,
    bearer_for,
    create_account,
    jmap_services_for,
    set_master_key,
)
from ...imap_fake import FakeFolder, FakeMailBox, make_message
from ...jmap_fake import HOST, PASSWORD, USER, FakeJmap

AGENT = ["mail.read", "mail.write", "drafts"]
REFUSED = "a message is not moved into the drafts folder"


class Account:
    """An account on a fake server, reached through the API."""

    def __init__(self, services: Services, account_id: str, several: bool) -> None:
        self.services = services
        self.id = account_id
        # Whether a message can be in several folders, and so join one.
        self.several = several
        self.app = create_app(Settings(storage="memory"), services)

    def holding(self, allow: list[str]) -> TestClient:
        grant = Grant(accounts=[self.id], allow=allow)
        return TestClient(self.app, headers=bearer_for(self.services, grant))

    def admin(self) -> TestClient:
        return TestClient(self.app, headers=admin_bearer(self.services))

    def url(self, rest: str = "") -> str:
        return f"/v1/accounts/{self.id}/messages{rest}"

    def drafts(self, draft_id: str = "") -> str:
        return f"/v1/accounts/{self.id}/drafts" + (f"/{draft_id}" if draft_id else "")

    def inbox(self, caller: TestClient) -> list[str]:
        answer = caller.get(self.url(), params={"folder": "inbox"})
        assert answer.status_code == 200, answer.text
        return [m["id"] for m in answer.json()["items"]]

    def folders_of(self, caller: TestClient, message_id: str) -> list[str]:
        answer = caller.get(self.url(f"/{message_id}"))
        assert answer.status_code == 200, answer.text
        folder_ids: list[str] = answer.json()["folder_ids"]
        return folder_ids

    def folder(self, caller: TestClient, role: str) -> str:
        folders = caller.get(f"/v1/accounts/{self.id}/folders").json()
        [found] = [f["id"] for f in folders if f["role"] == role]
        return str(found)


def on_imap(monkeypatch: pytest.MonkeyPatch) -> Account:
    box = FakeMailBox()
    box.folders = {
        "INBOX": FakeFolder(uidvalidity=7),
        "Drafts": FakeFolder(uidvalidity=3, flags=("\\Drafts",)),
        "Trash": FakeFolder(uidvalidity=5, flags=("\\Trash",)),
    }
    for uid in (1, 2, 3):
        box.add("INBOX", uid, make_message(f"Mail {uid}"))
    set_master_key(monkeypatch)

    def factory(
        kind: ProviderType, settings: ProviderSettings, credentials: CredentialReader
    ) -> Reads:
        return ImapProvider(
            settings,
            credentials,
            session_factory=lambda s: ImapSession(s, client_factory=box),
            timing=Timing(sleep=lambda seconds: None),
        )

    services = build_services(Settings(storage="memory"), provider_factory=factory)
    services.vault.initialize()
    account = create_account(
        services.accounts,
        ProviderType.IMAP,
        "me@example.com",
        settings={"host": "imap.example.com", "username": "me@example.com"},
        credentials={"password": SecretStr("secret")},
    )
    return Account(services, account.id, several=False)


def on_jmap(monkeypatch: pytest.MonkeyPatch) -> Account:
    server = FakeJmap()
    for n in (1, 2, 3):
        server.add_email(make_message(f"Mail {n}"))
    services = jmap_services_for(server, monkeypatch)
    account = create_account(
        services.accounts,
        ProviderType.JMAP,
        USER,
        settings={"host": HOST},
        credentials={"password": SecretStr(PASSWORD)},
    )
    return Account(services, account.id, several=True)


@pytest.fixture(params=[on_imap, on_jmap], ids=["imap", "jmap"])
def account(request: pytest.FixtureRequest, monkeypatch: pytest.MonkeyPatch) -> Account:
    make: Callable[[pytest.MonkeyPatch], Account] = request.param
    return make(monkeypatch)


def changes_into_drafts(account: Account, caller: TestClient) -> list[dict[str, Any]]:
    drafts = account.folder(caller, "drafts")
    changes: list[dict[str, Any]] = [
        {"folder_ids": ["drafts"]},
        {"folder_ids": [drafts]},
    ]
    if account.several:
        changes.append({"add_folder_ids": ["drafts"]})
    return changes


def test_a_change_puts_no_message_into_the_drafts_folder(account: Account) -> None:
    agent = account.holding(AGENT)
    first, *_ = account.inbox(agent)
    inbox = account.folders_of(agent, first)
    for changes in changes_into_drafts(account, agent):
        answer = agent.patch(account.url(f"/{first}"), json=changes)
        assert answer.status_code == 400, (changes, answer.text)
        assert answer.json()["error"]["message"] == REFUSED
        assert account.folders_of(agent, first) == inbox
    assert agent.delete(account.drafts(first)).status_code == 404
    assert first in account.inbox(agent)


def test_a_batch_puts_no_message_into_the_drafts_folder(account: Account) -> None:
    agent = account.holding(AGENT)
    ids = account.inbox(agent)
    for changes in changes_into_drafts(account, agent):
        answer = agent.post(
            account.url("/batch"),
            json={"action": "update", "ids": ids, "changes": changes},
        )
        assert answer.status_code == 200, answer.text
        results = answer.json()["results"]
        assert [r["error"]["message"] for r in results] == [REFUSED] * len(ids)
    assert account.inbox(agent) == ids
    for message_id in ids:
        assert agent.delete(account.drafts(message_id)).status_code == 404
    assert account.inbox(agent) == ids


def test_not_even_with_every_right(account: Account) -> None:
    admin = account.admin()
    first, *_ = account.inbox(admin)
    answer = admin.patch(account.url(f"/{first}"), json={"folder_ids": ["drafts"]})
    assert answer.status_code == 400, answer.text
    assert answer.json()["error"]["message"] == REFUSED


def test_a_draft_still_changes_goes_and_leaves(account: Account) -> None:
    agent = account.holding(AGENT)
    created = agent.post(account.drafts(), json={"subject": "Plan", "text": "x"})
    assert created.status_code == 201, created.text
    draft_id = created.json()["id"]
    drafts = account.folder(agent, "drafts")
    marked = agent.patch(
        account.url(f"/{draft_id}"), json={"unread": True, "folder_ids": [drafts]}
    )
    assert marked.status_code == 200, marked.text
    replaced = agent.put(
        account.drafts(draft_id), json={"subject": "Plan B", "text": "y"}
    )
    assert replaced.status_code == 200, replaced.text
    draft_id = replaced.json()["id"]
    moved = agent.patch(account.url(f"/{draft_id}"), json={"folder_ids": ["inbox"]})
    assert moved.status_code == 200, moved.text
    moved_id = moved.json()["id"]
    assert account.folders_of(agent, moved_id) == [account.folder(agent, "inbox")]
    other = agent.post(account.drafts(), json={"subject": "Gone", "text": "x"})
    assert agent.delete(account.drafts(other.json()["id"])).status_code == 204
