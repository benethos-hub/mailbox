"""Creating, renaming and deleting folders (CONCEPT 6.2)."""

from __future__ import annotations

import pytest
from fastapi.testclient import TestClient

from benethos_mailbox_api.data.models import Grant
from benethos_mailbox_api.data.providers.imap import mappers
from benethos_mailbox_api.data.providers.protocols.imap import ImapServer, ImapSession
from benethos_mailbox_api.errors import (
    BadRequestError,
    ConflictError,
    NotFoundError,
)
from benethos_mailbox_api.main import Services

from .conftest import bearer_for
from .imap_fake import FakeFolder, FakeMailBox
from .test_imap import provider, server  # noqa: F401 - the fixture


@pytest.fixture
def below_inbox() -> FakeMailBox:
    """A server that keeps every folder below the inbox, with "." between."""
    box = FakeMailBox()
    box.delimiter = "."
    box.namespace_prefix = "INBOX."
    box.announced = [*box.announced, "NAMESPACE"]
    box.folders = {"INBOX": FakeFolder(), "INBOX.Sent": FakeFolder(flags=("\\Sent",))}
    return box


# --- the IMAP adapter -------------------------------------------------------------


async def test_a_new_folder_goes_into_the_personal_namespace(
    below_inbox: FakeMailBox,
) -> None:
    folder = await provider(below_inbox).create_folder("Projekte", None)
    assert "INBOX.Projekte" in below_inbox.folders
    assert folder.id == mappers.folder_id("INBOX.Projekte")
    assert (folder.name, folder.subscribed) == ("Projekte", True)


async def test_a_subfolder(below_inbox: FakeMailBox) -> None:
    imap = provider(below_inbox)
    parent = await imap.create_folder("Kunden", None)
    child = await imap.create_folder("Müller GmbH", parent.id)
    assert "INBOX.Kunden.Müller GmbH" in below_inbox.folders
    assert child.parent_id == parent.id


@pytest.mark.parametrize(
    ("name", "parent", "error"),
    [
        ("a.b", None, BadRequestError),
        ("Sent", mappers.folder_id("INBOX"), ConflictError),
        ("New", mappers.folder_id("INBOX.Nowhere"), NotFoundError),
    ],
)
async def test_folders_that_cannot_be_made(
    below_inbox: FakeMailBox, name: str, parent: str | None, error: type[Exception]
) -> None:
    with pytest.raises(error):
        await provider(below_inbox).create_folder(name, parent)


async def test_rename_moves_the_subscription(below_inbox: FakeMailBox) -> None:
    imap = provider(below_inbox)
    folder = await imap.create_folder("Alt", None)
    renamed = await imap.update_folder(folder.id, "Neu", None)
    assert renamed.id == mappers.folder_id("INBOX.Neu")
    assert renamed.subscribed is True
    assert "INBOX.Alt" not in below_inbox.subscribed


async def test_a_folder_cannot_move_into_itself(below_inbox: FakeMailBox) -> None:
    imap = provider(below_inbox)
    outer = await imap.create_folder("Outer", None)
    inner = await imap.create_folder("Inner", outer.id)
    with pytest.raises(BadRequestError, match="into itself"):
        await imap.update_folder(outer.id, "Outer", inner.id)


async def test_delete_drops_the_subscription(below_inbox: FakeMailBox) -> None:
    imap = provider(below_inbox)
    folder = await imap.create_folder("Weg", None)
    await imap.delete_folder(folder.id)
    assert "INBOX.Weg" not in below_inbox.folders
    assert "INBOX.Weg" not in below_inbox.subscribed


async def test_without_namespace_at_the_top(server: FakeMailBox) -> None:  # noqa: F811
    await provider(server).create_folder("Projekte", None)
    assert "Projekte" in server.folders


def test_a_folder_that_is_gone_is_not_found() -> None:
    box = FakeMailBox()
    session = ImapSession(
        ImapServer("imap.example.com", 993, "tls"), client_factory=box
    )
    session.login("me@example.com", "secret")
    with pytest.raises(NotFoundError):
        session.select("Renamed by someone else")


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


def test_folders_with_a_role_stay(client: TestClient, account_id: str) -> None:
    url = f"/v1/accounts/{account_id}/folders"
    assert client.patch(f"{url}/inbox", json={"name": "Eingang"}).status_code == 409
    assert client.delete(f"{url}/sent").status_code == 409


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
