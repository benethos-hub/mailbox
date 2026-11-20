"""A change of a message's folders under grants narrowed to folders
(PERMISSIONS.md 8.5): a folder out of reach answers as one the account
lacks, so that a caller learns nothing of those it does not reach, and
a change that replaces a message's folders keeps it in those."""

from __future__ import annotations

from typing import Any

import pytest
from fastapi.testclient import TestClient

from benethos_mailbox_service.assembly import Services
from benethos_mailbox_service.data.models import Folder, Grant

from ...conftest import bearer_for, memory_of, relearn

SECRET = Folder(id="f_secret", name="Lawsuit")
MADE_UP = "f_made_up"


@pytest.fixture
def mailbox(services: Services, account_id: str) -> str:
    memory = memory_of(services, account_id)
    memory.folders.append(SECRET)
    relearn(services, account_id)
    return account_id


def narrowed(app_client: TestClient, services: Services, account_id: str) -> TestClient:
    grant = Grant(accounts=[account_id], allow=["mail.read", "mail.write"])
    narrow = grant.model_copy(update={"folders": ["inbox"]})
    return TestClient(app_client.app, headers=bearer_for(services, narrow))


def answers(client: TestClient, account_id: str, message_id: str, folder: str) -> Any:
    base = f"/v1/accounts/{account_id}/messages"
    patched = client.patch(f"{base}/{message_id}", json={"folder_ids": [folder]})
    batched = client.post(
        f"{base}/batch",
        json={
            "action": "update",
            "ids": [message_id],
            "changes": {"folder_ids": [folder]},
        },
    )
    return (
        (patched.status_code, patched.json()),
        (
            batched.status_code,
            batched.json()["results"] if batched.is_success else batched.json(),
        ),
    )


@pytest.mark.parametrize("message_id", ["m0", "no_such_mail"])
def test_a_folder_out_of_reach_answers_as_one_made_up(
    app_client: TestClient, services: Services, mailbox: str, message_id: str
) -> None:
    client = narrowed(app_client, services, mailbox)
    assert answers(client, mailbox, message_id, SECRET.id) == answers(
        client, mailbox, message_id, MADE_UP
    )
    memory = memory_of(services, mailbox)
    assert [m.folder_ids for m in memory.messages if m.id == "m0"] == [["inbox"]]


def test_without_folders_in_the_grant_a_made_up_folder_is_missing(
    client: TestClient, mailbox: str
) -> None:
    answer = client.patch(
        f"/v1/accounts/{mailbox}/messages/m0", json={"folder_ids": [MADE_UP]}
    )
    assert answer.status_code == 404
    assert answer.json()["error"]["message"] == f"folder {MADE_UP} not found"


def place(
    services: Services, account_id: str, message_id: str, folders: list[str]
) -> None:
    memory = memory_of(services, account_id)
    memory.messages = [
        m.model_copy(update={"folder_ids": folders}) if m.id == message_id else m
        for m in memory.messages
    ]


def folders_of(services: Services, account_id: str, message_id: str) -> list[str]:
    [found] = [
        m for m in memory_of(services, account_id).messages if m.id == message_id
    ]
    return list(found.folder_ids)


def test_a_change_that_replaces_folders_keeps_those_out_of_reach(
    app_client: TestClient, services: Services, mailbox: str
) -> None:
    place(services, mailbox, "m0", ["inbox", SECRET.id])
    client = narrowed(app_client, services, mailbox)
    base = f"/v1/accounts/{mailbox}/messages"
    replaced = client.patch(f"{base}/m0", json={"folder_ids": ["inbox"]})
    assert replaced.status_code == 403, replaced.text
    assert "out of these folders" in replaced.json()["error"]["message"]
    batched = client.post(
        f"{base}/batch",
        json={"action": "update", "ids": ["m0"], "changes": {"folder_ids": ["inbox"]}},
    )
    assert batched.json()["results"][0]["error"]["code"] == "forbidden"
    assert folders_of(services, mailbox, "m0") == ["inbox", SECRET.id]


def test_a_message_in_reached_folders_alone_moves_as_before(
    app_client: TestClient, services: Services, mailbox: str
) -> None:
    memory = memory_of(services, mailbox)
    memory.folders.append(Folder(id="f_inv", name="Invoices"))
    relearn(services, mailbox)
    grant = Grant(
        accounts=[mailbox],
        allow=["mail.read", "mail.write"],
        folders=["inbox", "Invoices"],
    )
    client = TestClient(app_client.app, headers=bearer_for(services, grant))
    moved = client.patch(
        f"/v1/accounts/{mailbox}/messages/m1", json={"folder_ids": ["f_inv"]}
    )
    assert moved.status_code == 200, moved.text
    assert folders_of(services, mailbox, "m1") == ["f_inv"]
