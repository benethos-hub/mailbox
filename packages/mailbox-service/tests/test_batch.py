"""POST .../messages/batch: one action for many messages (CONCEPT 6.3)."""

from __future__ import annotations

import pytest
from fastapi.testclient import TestClient

from benethos_mailbox_service.data.models import Grant, MessageUpdate
from benethos_mailbox_service.data.providers.imap import mappers
from benethos_mailbox_service.errors import MailboxServiceError, NotFoundError
from benethos_mailbox_service.main import Services

from .conftest import bearer_for
from .imap_fake import FakeMailBox, make_message
from .test_imap import FakeTime, provider, server  # noqa: F401 - the fixture

SENT = mappers.folder_id("Sent")
ARCHIVE = mappers.folder_id("Archive/2026")


def inbox(uid: int) -> str:
    return mappers.message_id("INBOX", 7, uid)


# --- the IMAP adapter: one round per folder --------------------------------------


async def test_one_store_per_set_of_changes(server: FakeMailBox) -> None:  # noqa: F811
    server.add("Sent", 1, make_message("Sent 1"))
    ids = [inbox(1), inbox(3), mappers.message_id("Sent", 1, 1)]
    results = await provider(server).update_messages(ids, MessageUpdate(starred=True))
    assert all(
        not isinstance(r, MailboxServiceError) and r.starred for r in results.values()
    )
    stores = [c for c in server.calls if c[0] == "store"]
    assert stores == [
        ("store", "+", (1, 3), ("\\Flagged",)),
        ("store", "+", (1,), ("\\Flagged",)),
    ]
    assert [c[1] for c in server.calls if c[0] == "select"] == ["INBOX", "Sent"]


async def test_keywords_differ_per_message(server: FakeMailBox) -> None:  # noqa: F811
    raw, _ = server.folders["INBOX"].messages[3]
    server.folders["INBOX"].messages[3] = (raw, ("$Forwarded",))
    await provider(server).update_messages(
        [inbox(3), inbox(4)], MessageUpdate(keywords=["$forwarded"])
    )
    # Message 3 has the keyword already: only message 4 gets it.
    assert [c for c in server.calls if c[0] == "store"] == [
        ("store", "+", (4,), ("$Forwarded",))
    ]


async def test_one_move_for_many(server: FakeMailBox) -> None:  # noqa: F811
    results = await provider(server).update_messages(
        [inbox(1), inbox(2), inbox(5)], MessageUpdate(folder_ids=[ARCHIVE])
    )
    assert [c for c in server.calls if c[0] == "move"] == [
        ("move", (1, 2, 5), "Archive/2026")
    ]
    new = {r.id for r in results.values() if not isinstance(r, MailboxServiceError)}
    assert new == {mappers.message_id("Archive/2026", 1, uid) for uid in (1, 2, 3)}


async def test_unknown_ones_fail_alone(server: FakeMailBox) -> None:  # noqa: F811
    results = await provider(server).update_messages(
        [inbox(1), inbox(99), "junk", mappers.message_id("INBOX", 6, 2)],
        MessageUpdate(unread=False),
    )
    assert not isinstance(results[inbox(1)], MailboxServiceError)
    for bad in (inbox(99), "junk", mappers.message_id("INBOX", 6, 2)):
        assert isinstance(results[bad], NotFoundError)


async def test_a_batch_is_paced_per_folder_not_per_message(
    server: FakeMailBox,  # noqa: F811
) -> None:
    for uid in range(100, 200):
        server.add("INBOX", uid, make_message(f"Bulk {uid}"))
    time = FakeTime()
    imap = provider(server, time, max_requests_per_minute=60)
    ids = [inbox(uid) for uid in range(100, 200)]
    results = await imap.update_messages(ids, MessageUpdate(unread=False))
    assert len(results) == 100
    assert time.sleeps == []


async def test_a_batch_into_the_trash(server: FakeMailBox) -> None:  # noqa: F811
    server.folders["Trash"] = server.folders.pop("Archive")
    server.folders["Trash"].flags = ("\\Trash",)
    results = await provider(server).delete_messages(
        [inbox(1), inbox(2)], permanent=False
    )
    assert all(
        r is not None and r.folder_ids == [mappers.folder_id("Trash")]
        for r in results.values()
        if not isinstance(r, MailboxServiceError)
    )
    assert [c for c in server.calls if c[0] == "move"] == [("move", (1, 2), "Trash")]


# --- the API -------------------------------------------------------------------------


def test_batch_update(client: TestClient, account_id: str) -> None:
    answer = client.post(
        f"/v1/accounts/{account_id}/messages/batch",
        json={
            "action": "update",
            "ids": ["m0", "nope", "m1", "m0"],
            "changes": {"starred": True},
        },
    )
    assert answer.status_code == 200
    results = answer.json()["results"]
    # One result per id, in order, duplicates once.
    assert [r["id"] for r in results] == ["m0", "nope", "m1"]
    assert results[0]["ok"] is True
    assert results[0]["message"]["starred"] is True
    assert results[1] == {
        "id": "nope",
        "ok": False,
        "message": None,
        "error": {"code": "not_found", "message": "message nope not found"},
    }


@pytest.mark.parametrize(
    "body",
    [
        {"action": "update", "ids": ["m0"]},
        {"action": "update", "ids": [], "changes": {"starred": True}},
        {"action": "update", "ids": ["m"] * 101, "changes": {"starred": True}},
        {"action": "archive", "ids": ["m0"]},
    ],
)
def test_batch_refuses_bad_requests(
    client: TestClient, account_id: str, body: dict[str, object]
) -> None:
    answer = client.post(f"/v1/accounts/{account_id}/messages/batch", json=body)
    assert answer.status_code == 422


def test_batch_needs_the_rights_of_its_action(
    app_client: TestClient, services: Services, account_id: str
) -> None:
    url = f"/v1/accounts/{account_id}/messages/batch"
    delete_all = {"action": "delete", "ids": ["m0", "m1"], "permanent": True}
    writer = bearer_for(services, Grant(accounts=[account_id], allow=["mail.write"]))
    answer = app_client.post(url, json=delete_all, headers=writer)
    assert answer.status_code == 403
    assert "delete_message_permanent" in answer.json()["error"]["message"]

    only_deleting = bearer_for(
        services, Grant(accounts=[account_id], allow=["mail.delete"])
    )
    answer = app_client.post(url, json=delete_all, headers=only_deleting)
    assert answer.status_code == 403
    assert "batch_messages" in answer.json()["error"]["message"]

    both = bearer_for(
        services, Grant(accounts=[account_id], allow=["mail.write", "mail.delete"])
    )
    answer = app_client.post(url, json=delete_all, headers=both)
    assert answer.status_code == 200
    assert [r["ok"] for r in answer.json()["results"]] == [True, True]
