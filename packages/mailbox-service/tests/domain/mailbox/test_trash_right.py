"""A move into the trash is a deletion: it needs delete_message beside
update_message, by a single update and by a batch, and where the grants
narrow it to folders, on the folder of each message. Out of the trash
and into junk need update_message alone."""

from __future__ import annotations

import pytest
from fastapi.testclient import TestClient

from benethos_mailbox_service.assembly import Services
from benethos_mailbox_service.data.models import Folder, FolderRole, Grant

from ...conftest import bearer_for, memory_of, relearn

TRASH = Folder(id="f_trash", name="Trash", role=FolderRole.TRASH)
JUNK = Folder(id="f_junk", name="Junk", role=FolderRole.JUNK)
INVOICES = Folder(id="f_inv", name="Invoices")
MARKS_AND_MOVES = ["mail.read", "update_message", "batch_messages"]


@pytest.fixture
def trash_box(services: Services, account_id: str) -> str:
    memory = memory_of(services, account_id)
    memory.folders += [TRASH, JUNK, INVOICES]
    relearn(services, account_id)
    # m1 in Invoices, the others in the inbox.
    memory.messages = [
        m.model_copy(update={"folder_ids": ["f_inv" if m.id == "m1" else "inbox"]})
        for m in memory.messages
    ]
    return account_id


def holding(
    app_client: TestClient, services: Services, account_id: str, allow: list[str]
) -> TestClient:
    """A client whose one grant allows ``allow`` on the account, in every
    folder."""
    grant = Grant(accounts=[account_id], allow=allow)
    return TestClient(app_client.app, headers=bearer_for(services, grant))


def deleting_in_invoices(
    app_client: TestClient, services: Services, account_id: str
) -> TestClient:
    """A client that may mark and move everywhere, and delete in Invoices
    alone."""
    grants = (
        Grant(accounts=[account_id], allow=MARKS_AND_MOVES),
        Grant(accounts=[account_id], allow=["delete_message"], folders=["Invoices"]),
    )
    return TestClient(app_client.app, headers=bearer_for(services, *grants))


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


def test_the_trash_takes_only_what_delete_message_reaches(
    app_client: TestClient, services: Services, trash_box: str
) -> None:
    """As DELETE: a message outside the folders of delete_message stays."""
    narrowed = deleting_in_invoices(app_client, services, trash_box)
    base = f"/v1/accounts/{trash_box}/messages"
    assert narrowed.delete(f"{base}/m0").status_code == 404
    refused = narrowed.patch(f"{base}/m0", json={"folder_ids": ["trash"]})
    assert refused.status_code == 403, refused.text
    assert "delete_message into the trash" in refused.json()["error"]["message"]
    assert folders_of(services, trash_box, "m0") == ["inbox"]
    moved = narrowed.patch(f"{base}/m1", json={"folder_ids": ["trash"]})
    assert moved.status_code == 200, moved.text
    assert folders_of(services, trash_box, "m1") == ["f_trash"]


def test_a_batch_into_the_trash_refuses_each_message_out_of_reach(
    app_client: TestClient, services: Services, trash_box: str
) -> None:
    narrowed = deleting_in_invoices(app_client, services, trash_box)
    answer = narrowed.post(
        f"/v1/accounts/{trash_box}/messages/batch",
        json={
            "action": "update",
            "ids": ["m0", "m1"],
            "changes": {"folder_ids": ["trash"]},
        },
    ).json()
    outcome = {r["id"]: r for r in answer["results"]}
    assert outcome["m0"]["error"]["code"] == "forbidden"
    assert outcome["m1"]["ok"] is True
    assert folders_of(services, trash_box, "m0") == ["inbox"]
    assert folders_of(services, trash_box, "m1") == ["f_trash"]


def test_a_folder_the_account_does_not_list_is_missing(
    app_client: TestClient, services: Services, trash_box: str
) -> None:
    """Another name of the trash, such as another spelling of its id,
    passes no rule: every folder a change names is one the account
    lists."""
    marker = holding(app_client, services, trash_box, MARKS_AND_MOVES)
    base = f"/v1/accounts/{trash_box}/messages"
    answer = marker.patch(f"{base}/m0", json={"folder_ids": ["f_unlisted"]})
    assert answer.status_code == 404, answer.text
    assert answer.json()["error"]["message"] == "folder f_unlisted not found"
    batch = marker.post(
        f"{base}/batch",
        json={
            "action": "update",
            "ids": ["m0"],
            "changes": {"folder_ids": ["f_unlisted"]},
        },
    )
    assert batch.status_code == 404, batch.text
    assert folders_of(services, trash_box, "m0") == ["inbox"]


def test_a_folder_goes_only_into_a_folder_the_account_lists(
    app_client: TestClient, services: Services, trash_box: str
) -> None:
    mover = holding(app_client, services, trash_box, ["mail.read", "update_folder"])
    answer = mover.patch(
        f"/v1/accounts/{trash_box}/folders/f_inv", json={"parent_id": "f_unlisted"}
    )
    assert answer.status_code == 404, answer.text
    assert answer.json()["error"]["message"] == "folder f_unlisted not found"
    maker = holding(app_client, services, trash_box, ["mail.read", "create_folder"])
    made = maker.post(
        f"/v1/accounts/{trash_box}/folders",
        json={"name": "New", "parent_id": "f_unlisted"},
    )
    assert made.status_code == 404, made.text


KEPT = Folder(id="f_kept", name="Kept", parent_id="f_trash")


@pytest.fixture
def kept_box(services: Services, trash_box: str) -> str:
    """The trash with a folder below it."""
    memory_of(services, trash_box).folders.append(KEPT)
    relearn(services, trash_box)
    return trash_box


def test_a_folder_below_the_trash_is_the_trash(
    app_client: TestClient, services: Services, kept_box: str
) -> None:
    marker = holding(app_client, services, kept_box, MARKS_AND_MOVES)
    base = f"/v1/accounts/{kept_box}/messages"
    answer = marker.patch(f"{base}/m0", json={"folder_ids": ["f_kept"]})
    assert answer.status_code == 403, answer.text
    assert "delete_message" in answer.json()["error"]["message"]
    batch = marker.post(
        f"{base}/batch",
        json={"action": "update", "ids": ["m0"], "changes": {"folder_ids": ["f_kept"]}},
    )
    assert batch.status_code == 403, batch.text
    assert folders_of(services, kept_box, "m0") == ["inbox"]


def test_a_folder_below_the_trash_needs_delete_message(
    app_client: TestClient, services: Services, kept_box: str
) -> None:
    folder = f"/v1/accounts/{kept_box}/folders/f_inv"
    mover = holding(app_client, services, kept_box, ["mail.read", "update_folder"])
    refused = mover.patch(folder, json={"parent_id": "trash"})
    assert refused.status_code == 403, refused.text
    assert "delete_message" in refused.json()["error"]["message"]
    assert mover.patch(folder, json={"parent_id": "f_kept"}).status_code == 403
    deleter = holding(
        app_client, services, kept_box, ["mail.read", "update_folder", "delete_message"]
    )
    moved = deleter.patch(folder, json={"parent_id": "trash"})
    assert moved.status_code == 200, moved.text
    assert moved.json()["parent_id"] == "f_trash"


def test_a_folder_out_of_the_trash_needs_update_folder_alone(
    app_client: TestClient, services: Services, kept_box: str
) -> None:
    mover = holding(app_client, services, kept_box, ["mail.read", "update_folder"])
    answer = mover.patch(
        f"/v1/accounts/{kept_box}/folders/f_kept", json={"parent_id": None}
    )
    assert answer.status_code == 200, answer.text
    assert answer.json()["parent_id"] is None


def test_a_folder_below_the_trash_goes_only_where_delete_message_reaches(
    app_client: TestClient, services: Services, kept_box: str
) -> None:
    """As a message: the folder moved must be one delete_message reaches."""
    grants = (
        Grant(accounts=[kept_box], allow=["mail.read", "update_folder"]),
        Grant(accounts=[kept_box], allow=["delete_message"], folders=["Kept"]),
    )
    narrowed = TestClient(app_client.app, headers=bearer_for(services, *grants))
    answer = narrowed.patch(
        f"/v1/accounts/{kept_box}/folders/f_inv", json={"parent_id": "trash"}
    )
    assert answer.status_code == 403, answer.text
    assert "delete_message into the trash" in answer.json()["error"]["message"]


def test_a_batch_that_reaches_no_message_answers_each_as_the_single_route(
    app_client: TestClient, services: Services, trash_box: str
) -> None:
    """Without delete_message, a batch into the trash whose messages all
    lie outside the grants answers 404 for each, as PATCH does for one,
    not 403 for the whole batch."""
    grant = Grant(accounts=[trash_box], allow=MARKS_AND_MOVES, folders=["Invoices"])
    narrowed = TestClient(app_client.app, headers=bearer_for(services, grant))
    base = f"/v1/accounts/{trash_box}/messages"
    single = narrowed.patch(f"{base}/m0", json={"folder_ids": ["trash"]})
    assert single.status_code == 404, single.text
    answer = narrowed.post(
        f"{base}/batch",
        json={"action": "update", "ids": ["m0"], "changes": {"folder_ids": ["trash"]}},
    )
    assert answer.status_code == 200, answer.text
    [result] = answer.json()["results"]
    assert result["error"]["code"] == "not_found"
    assert folders_of(services, trash_box, "m0") == ["inbox"]
