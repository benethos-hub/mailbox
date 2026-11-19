"""A move into the trash is a deletion: it needs delete_message beside
update_message, by a single update and by a batch. Out of the trash and
into junk need update_message alone."""

from __future__ import annotations

import pytest
from fastapi.testclient import TestClient

from benethos_mailbox_service.assembly import Services
from benethos_mailbox_service.data.models import Folder, FolderRole, Grant

from ...conftest import bearer_for, memory_of, relearn

TRASH = Folder(id="f_trash", name="Trash", role=FolderRole.TRASH)
JUNK = Folder(id="f_junk", name="Junk", role=FolderRole.JUNK)
MARKS_AND_MOVES = ["mail.read", "update_message", "batch_messages"]


@pytest.fixture
def trash_box(services: Services, account_id: str) -> str:
    memory = memory_of(services, account_id)
    memory.folders += [TRASH, JUNK]
    relearn(services, account_id)
    return account_id


def holding(
    app_client: TestClient, services: Services, account_id: str, allow: list[str]
) -> TestClient:
    """A client whose one grant allows ``allow`` on the account, in every
    folder."""
    grant = Grant(accounts=[account_id], allow=allow)
    return TestClient(app_client.app, headers=bearer_for(services, grant))


def folders_of(services: Services, account_id: str, message_id: str) -> list[str]:
    [message] = [
        m for m in memory_of(services, account_id).messages if m.id == message_id
    ]
    return list(message.folder_ids)


@pytest.mark.parametrize("trash", ["trash", "f_trash"])
def test_a_move_into_the_trash_needs_delete_message(
    app_client: TestClient, services: Services, trash_box: str, trash: str
) -> None:
    marker = holding(app_client, services, trash_box, MARKS_AND_MOVES)
    answer = marker.patch(
        f"/v1/accounts/{trash_box}/messages/m0", json={"folder_ids": [trash]}
    )
    assert answer.status_code == 403, answer.text
    assert "delete_message" in answer.json()["error"]["message"]
    assert folders_of(services, trash_box, "m0") == ["inbox"]


def test_a_batch_into_the_trash_needs_delete_message(
    app_client: TestClient, services: Services, trash_box: str
) -> None:
    marker = holding(app_client, services, trash_box, MARKS_AND_MOVES)
    answer = marker.post(
        f"/v1/accounts/{trash_box}/messages/batch",
        json={"action": "update", "ids": ["m0"], "changes": {"folder_ids": ["trash"]}},
    )
    assert answer.status_code == 403, answer.text
    assert "delete_message" in answer.json()["error"]["message"]
    assert folders_of(services, trash_box, "m0") == ["inbox"]


def test_marks_junk_and_out_of_the_trash_need_update_message_alone(
    app_client: TestClient, services: Services, trash_box: str
) -> None:
    marker = holding(app_client, services, trash_box, MARKS_AND_MOVES)
    base = f"/v1/accounts/{trash_box}/messages"
    assert marker.patch(f"{base}/m0", json={"unread": False}).status_code == 200
    assert marker.patch(f"{base}/m0", json={"folder_ids": ["junk"]}).status_code == 200
    assert folders_of(services, trash_box, "m0") == ["f_junk"]
    memory = memory_of(services, trash_box)
    memory.messages = [
        m.model_copy(update={"folder_ids": ["f_trash"]}) if m.id == "m1" else m
        for m in memory.messages
    ]
    assert marker.patch(f"{base}/m1", json={"folder_ids": ["inbox"]}).status_code == 200
    assert folders_of(services, trash_box, "m1") == ["inbox"]


@pytest.mark.parametrize(
    "allow",
    [["mail.read", "update_message", "delete_message"], ["mail.read", "mail.write"]],
)
def test_with_delete_message_the_move_into_the_trash_goes(
    app_client: TestClient, services: Services, trash_box: str, allow: list[str]
) -> None:
    writer = holding(app_client, services, trash_box, allow)
    answer = writer.patch(
        f"/v1/accounts/{trash_box}/messages/m0", json={"folder_ids": ["trash"]}
    )
    assert answer.status_code == 200, answer.text
    assert folders_of(services, trash_box, "m0") == ["f_trash"]
