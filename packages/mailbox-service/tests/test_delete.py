"""Deleting a message: into the trash, or for good (CONCEPT 6.3, 7.5)."""

from __future__ import annotations

import pytest
from fastapi.testclient import TestClient

from benethos_mailbox_service.data.models import Grant
from benethos_mailbox_service.data.providers.imap import mappers
from benethos_mailbox_service.errors import ConflictError, NotSupportedError
from benethos_mailbox_service.main import Services

from .conftest import bearer_for
from .imap_fake import FakeFolder, FakeMailBox
from .provider_ops import delete
from .test_imap import provider, server  # noqa: F401 - the fixture

MESSAGE = mappers.message_id("INBOX", 7, 3)


@pytest.fixture
def with_trash(server: FakeMailBox) -> FakeMailBox:  # noqa: F811
    server.folders["Trash"] = FakeFolder(flags=("\\Trash",))
    return server


# --- the IMAP adapter -----------------------------------------------------------


async def test_into_the_trash(with_trash: FakeMailBox) -> None:
    trashed = await delete(provider(with_trash), MESSAGE, permanent=False)
    assert trashed is not None
    assert trashed.folder_ids == [mappers.folder_id("Trash")]
    assert trashed.subject == "Invoice 3"
    assert 3 not in with_trash.folders["INBOX"].messages
    assert len(with_trash.folders["Trash"].messages) == 1


async def test_from_the_trash_only_for_good(with_trash: FakeMailBox) -> None:
    imap = provider(with_trash)
    trashed = await delete(imap, MESSAGE, permanent=False)
    assert trashed is not None
    with pytest.raises(ConflictError, match="in the trash already"):
        await delete(imap, trashed.id, permanent=False)
    assert await delete(imap, trashed.id, permanent=True) is None
    assert with_trash.folders["Trash"].messages == {}


async def test_no_trash_no_deletion(server: FakeMailBox) -> None:  # noqa: F811
    with pytest.raises(ConflictError, match="no trash folder"):
        await delete(provider(server), MESSAGE, permanent=False)
    assert 3 in server.folders["INBOX"].messages


async def test_for_good_only_this_message(server: FakeMailBox) -> None:  # noqa: F811
    # Another client marked a message deleted and has not expunged yet.
    raw, _ = server.folders["INBOX"].messages[4]
    server.folders["INBOX"].messages[4] = (raw, ("\\Deleted",))
    assert await delete(provider(server), MESSAGE, permanent=True) is None
    assert 3 not in server.folders["INBOX"].messages
    assert 4 in server.folders["INBOX"].messages
    assert ("expunge", (3,)) in server.calls


async def test_for_good_needs_uidplus(server: FakeMailBox) -> None:  # noqa: F811
    server.announced = ["IMAP4REV1", "MOVE"]
    with pytest.raises(NotSupportedError, match="UIDPLUS"):
        await delete(provider(server), MESSAGE, permanent=True)
    assert 3 in server.folders["INBOX"].messages


# --- the API and its rights ------------------------------------------------------


def test_delete_without_a_trash_folder(client: TestClient, account_id: str) -> None:
    # The memory account has an inbox and a sent folder only.
    answer = client.delete(f"/v1/accounts/{account_id}/messages/m0")
    assert answer.status_code == 409
    assert answer.json()["error"]["code"] == "conflict"


def test_deleting_for_good_is_its_own_right(
    app_client: TestClient, services: Services, account_id: str
) -> None:
    url = f"/v1/accounts/{account_id}/messages/m1"
    writer = bearer_for(
        services, Grant(accounts=[account_id], allow=["mail.read", "mail.write"])
    )
    answer = app_client.delete(url, params={"permanent": True}, headers=writer)
    assert answer.status_code == 403
    assert "delete_message_permanent" in answer.json()["error"]["message"]

    deleter = bearer_for(
        services, Grant(accounts=[account_id], allow=["mail.read", "mail.delete"])
    )
    answer = app_client.delete(url, params={"permanent": True}, headers=deleter)
    assert answer.status_code == 204
    assert app_client.get(url, headers=deleter).status_code == 404
