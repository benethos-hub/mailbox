"""Creating, renaming and deleting folders (CONCEPT 6.2)."""

from __future__ import annotations

from fastapi.testclient import TestClient

from benethos_mailbox_service.assembly import Services, build_services, create_app
from benethos_mailbox_service.config import Settings
from benethos_mailbox_service.data.models import (
    Folder,
    FolderRole,
    Grant,
    Message,
    ProviderType,
)
from benethos_mailbox_service.data.providers.memory import MemoryProvider

from ...conftest import admin_bearer, bearer_for, create_account

# --- the API and its rights ----------------------------------------------------------


def test_create_rename_delete(client: TestClient, account_id: str) -> None:
    url = f"/v1/accounts/{account_id}/folders"
    created = client.post(url, json={"name": "Rechnungen"})
    assert created.status_code == 201
    folder_id = created.json()["id"]
    renamed = client.patch(f"{url}/{folder_id}", json={"name": "Belege"})
    assert renamed.status_code == 200
    assert renamed.json()["name"] == "Belege"
    assert client.delete(f"{url}/{folder_id}").status_code == 204
    assert folder_id not in {f["id"] for f in client.get(url).json()}


def test_a_role_names_a_folder(messages: list[Message]) -> None:
    """In place of an id: the parent of a new folder, the target of a move."""
    adapter = MemoryProvider(
        folders=[
            Folder(id="f1", name="Inbox", role=FolderRole.INBOX),
            Folder(id="f2", name="Archive", role=FolderRole.ARCHIVE),
        ],
        messages=messages,
    )
    settings = Settings(storage="memory")
    services = build_services(settings, provider_factory=lambda *_: adapter)
    account_id = create_account(
        services.accounts, ProviderType.MEMORY, "a@x.example"
    ).id
    client = TestClient(create_app(settings, services), headers=admin_bearer(services))
    url = f"/v1/accounts/{account_id}"
    created = client.post(
        f"{url}/folders", json={"name": "2026", "parent_id": "archive"}
    )
    assert created.status_code == 201, created.text
    assert created.json()["parent_id"] == "f2"
    one = client.patch(f"{url}/messages/m1", json={"folder_ids": ["archive"]})
    assert one.status_code == 200, one.text
    assert one.json()["folder_ids"] == ["f2"]
    batch = {"ids": ["m0"], "action": "update", "changes": {"folder_ids": ["archive"]}}
    moved = client.post(f"{url}/messages/batch", json=batch).json()["results"][0]
    assert moved["message"]["folder_ids"] == ["f2"]
    missing = client.patch(f"{url}/messages/m2", json={"folder_ids": ["junk"]})
    assert missing.status_code == 501
    assert "no junk folder" in missing.json()["error"]["message"]


def test_folders_with_a_role_stay(client: TestClient, account_id: str) -> None:
    url = f"/v1/accounts/{account_id}/folders"
    assert client.patch(f"{url}/inbox", json={"name": "Eingang"}).status_code == 409
    assert client.delete(f"{url}/sent").status_code == 409


def test_a_folder_moves_under_a_role(client: TestClient, account_id: str) -> None:
    url = f"/v1/accounts/{account_id}/folders"
    folder = client.post(url, json={"name": "Old"}).json()["id"]
    sent = next(f["id"] for f in client.get(url).json() if f.get("role") == "sent")
    moved = client.patch(f"{url}/{folder}", json={"parent_id": "sent"})
    assert moved.status_code == 200
    assert moved.json()["parent_id"] == sent


def test_only_empty_folders_without_subfolders_go(
    client: TestClient, account_id: str
) -> None:
    url = f"/v1/accounts/{account_id}/folders"
    parent = client.post(url, json={"name": "Oben"}).json()["id"]
    client.post(url, json={"name": "Unten", "parent_id": parent})
    answer = client.delete(f"{url}/{parent}")
    assert answer.status_code == 409
    assert "subfolders" in answer.json()["error"]["message"]

    full = client.post(url, json={"name": "Voll"}).json()["id"]
    client.patch(f"/v1/accounts/{account_id}/messages/m0", json={"folder_ids": [full]})
    answer = client.delete(f"{url}/{full}")
    assert answer.status_code == 409
    assert "holds 1 messages" in answer.json()["error"]["message"]


def test_deleting_a_folder_needs_mail_delete(
    app_client: TestClient, services: Services, account_id: str
) -> None:
    url = f"/v1/accounts/{account_id}/folders"
    writer = bearer_for(services, Grant(accounts=[account_id], allow=["mail.write"]))
    created = app_client.post(url, json={"name": "Tmp"}, headers=writer)
    assert created.status_code == 201
    folder_id = created.json()["id"]
    assert app_client.delete(f"{url}/{folder_id}", headers=writer).status_code == 403
    deleter = bearer_for(
        services, Grant(accounts=[account_id], allow=["mail.read", "mail.delete"])
    )
    assert app_client.delete(f"{url}/{folder_id}", headers=deleter).status_code == 204
