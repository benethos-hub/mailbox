"""A Gmail account under a grant narrowed to folders (PERMISSIONS.md 8.5):
a change that replaces a message's labels keeps those out of reach, while
labels in reach join and leave, and All Mail, which holds every message,
refuses nothing by itself."""

from __future__ import annotations

import pytest
from fastapi.testclient import TestClient

from benethos_mailbox_service.assembly import create_app
from benethos_mailbox_service.config import Settings
from benethos_mailbox_service.data.models import Grant

from ..conformance_helpers import box, services_of
from ..conftest import bearer_for


@pytest.fixture
def gmail(monkeypatch: pytest.MonkeyPatch) -> tuple[TestClient, str, dict[str, str]]:
    """A client narrowed to the inbox and Kept, the account's id, and the
    ids of the labels Lawsuit and Kept."""
    found = box("gmail")
    lawsuit = found.fake.new_label("Lawsuit")
    kept = found.fake.new_label("Kept")
    found.fake.add_message(labels=("INBOX", lawsuit), subject="Both")
    found.fake.add_message(labels=("INBOX",), subject="Inbox")
    services, account_id = services_of(found, monkeypatch)
    grant = Grant(
        accounts=[account_id],
        allow=["mail.read", "mail.write"],
        folders=["inbox", "Kept"],
    )
    client = TestClient(
        create_app(Settings(storage="memory"), services),
        headers=bearer_for(services, grant),
    )
    return client, account_id, {"lawsuit": lawsuit, "kept": kept}


def by_subject(client: TestClient, account_id: str) -> dict[str, dict[str, object]]:
    listed = client.get(
        f"/v1/accounts/{account_id}/messages", params={"folder": "inbox"}
    )
    assert listed.status_code == 200, listed.text
    return {m["subject"]: m for m in listed.json()["items"]}


def test_replacing_the_labels_keeps_one_out_of_reach(
    gmail: tuple[TestClient, str, dict[str, str]],
) -> None:
    client, account_id, labels = gmail
    both = by_subject(client, account_id)["Both"]
    url = f"/v1/accounts/{account_id}/messages/{both['id']}"
    replaced = client.patch(url, json={"folder_ids": ["inbox"]})
    assert replaced.status_code == 403, replaced.text
    assert "out of these folders" in replaced.json()["error"]["message"]
    assert labels["lawsuit"] in client.get(url).json()["folder_ids"]
    added = client.patch(url, json={"add_folder_ids": [labels["kept"]]})
    assert added.status_code == 200, added.text
    removed = client.patch(url, json={"remove_folder_ids": [labels["kept"]]})
    assert removed.status_code == 200, removed.text
    assert labels["lawsuit"] in removed.json()["folder_ids"]


def test_all_mail_refuses_no_move_by_itself(
    gmail: tuple[TestClient, str, dict[str, str]],
) -> None:
    client, account_id, labels = gmail
    inbox = by_subject(client, account_id)["Inbox"]
    assert len(inbox["folder_ids"]) > 1  # the inbox and All Mail
    url = f"/v1/accounts/{account_id}/messages/{inbox['id']}"
    moved = client.patch(url, json={"folder_ids": [labels["kept"]]})
    assert moved.status_code == 200, moved.text
    assert labels["kept"] in moved.json()["folder_ids"]
