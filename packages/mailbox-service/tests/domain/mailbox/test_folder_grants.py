"""Grants narrowed to folders (PERMISSIONS.md 8.5): reading, writing and
deleting only there and in their subfolders, moves among them, the trash
always reachable to delete into, the lists across accounts, the change
feed and replies filtered."""

from __future__ import annotations

from datetime import UTC, datetime
from typing import Any

import pytest
from fastapi.testclient import TestClient

from benethos_mailbox_service.assembly import Services
from benethos_mailbox_service.data.models import (
    ChangeRecord,
    Folder,
    FolderRole,
    Grant,
)
from benethos_mailbox_service.domain.mailbox.reach import Reach
from benethos_mailbox_service.domain.rights.access import Access

from ...conftest import bearer_for, memory_of

INVOICES = Folder(id="f_inv", name="Invoices")
YEAR = Folder(id="f_2026", name="2026", parent_id="f_inv")
PRIVATE = Folder(id="f_priv", name="Private")
TRASH = Folder(id="trash", name="Trash", role=FolderRole.TRASH)
# m0 in the inbox, m1 in Invoices, m2 in Invoices/2026, m3 in Private.
PLACES = {"m0": "inbox", "m1": "f_inv", "m2": "f_2026", "m3": "f_priv"}


@pytest.fixture
def mailbox(services: Services, account_id: str) -> str:
    memory = memory_of(services, account_id)
    memory.folders += [INVOICES, YEAR, PRIVATE, TRASH]
    memory.messages = [
        m.model_copy(update={"folder_ids": [PLACES.get(m.id, "inbox")]})
        for m in memory.messages
    ]
    return account_id


def caller(
    app_client: TestClient,
    services: Services,
    account_id: str,
    *grants: tuple[list[str], list[str]],
) -> TestClient:
    """A client whose grants are ``(allow, folders)`` on the account."""
    headers = bearer_for(
        services,
        *(Grant(accounts=[account_id], allow=a, folders=f) for a, f in grants),
    )
    return TestClient(app_client.app, headers=headers)


def ids(answer: Any) -> list[str]:
    return sorted(m["id"] for m in answer.json()["items"])


# --- reading --------------------------------------------------------------------


def test_only_the_listed_folders_and_their_subfolders_are_seen(
    app_client: TestClient, services: Services, mailbox: str
) -> None:
    reader = caller(app_client, services, mailbox, (["mail.read"], ["Invoices"]))
    base = f"/v1/accounts/{mailbox}"
    folders = reader.get(f"{base}/folders").json()
    assert sorted(f["id"] for f in folders) == ["f_2026", "f_inv"]
    assert ids(reader.get(f"{base}/messages")) == ["m1", "m2"]
    assert ids(reader.get(f"{base}/messages", params={"folder": "f_inv"})) == ["m1"]
    outside = reader.get(f"{base}/messages", params={"folder": "f_priv"})
    assert outside.status_code == 404
    assert reader.get(f"{base}/messages", params={"folder": "inbox"}).status_code == 404
    assert reader.get(f"{base}/messages/m2").status_code == 200
    for path in ("m3", "m0", "m3/raw", "m3/attachments/att_0"):
        assert reader.get(f"{base}/messages/{path}").status_code == 404, path


def test_a_folder_is_named_by_role_name_or_id(
    app_client: TestClient, services: Services, mailbox: str
) -> None:
    reader = caller(app_client, services, mailbox, (["mail.read"], ["inbox", "f_priv"]))
    assert ids(reader.get(f"/v1/accounts/{mailbox}/messages")) == ["m0", "m3", "m4"]


def test_the_lists_across_accounts_keep_to_the_folders(
    app_client: TestClient, services: Services, mailbox: str
) -> None:
    reader = caller(app_client, services, mailbox, (["mail.read"], ["Invoices"]))
    assert ids(reader.get("/v1/messages")) == ["m1", "m2"]
    inbox = reader.get("/v1/messages", params={"folder": "inbox"})
    assert ids(inbox) == []


def test_two_grants_see_both_their_folders(
    app_client: TestClient, services: Services, mailbox: str
) -> None:
    reader = caller(
        app_client,
        services,
        mailbox,
        (["mail.read"], ["Invoices"]),
        (["mail.read"], ["Private"]),
    )
    assert ids(reader.get(f"/v1/accounts/{mailbox}/messages")) == ["m1", "m2", "m3"]


def test_a_grant_on_every_folder_is_not_narrowed(
    app_client: TestClient, services: Services, mailbox: str
) -> None:
    reader = caller(
        app_client,
        services,
        mailbox,
        (["mail.read"], ["Invoices"]),
        (["get_message"], None),  # type: ignore[arg-type]
    )
    assert reader.get(f"/v1/accounts/{mailbox}/messages/m3").status_code == 200
    assert ids(reader.get(f"/v1/accounts/{mailbox}/messages")) == ["m1", "m2"]


# --- writing --------------------------------------------------------------------


def test_moves_stay_among_the_folders_of_one_grant(
    app_client: TestClient, services: Services, mailbox: str
) -> None:
    writer = caller(
        app_client,
        services,
        mailbox,
        (["mail.read", "mail.write"], ["Invoices"]),
        (["mail.read", "mail.write"], ["Private"]),
    )
    base = f"/v1/accounts/{mailbox}/messages"
    within = writer.patch(f"{base}/m1", json={"folder_ids": ["f_2026"]})
    assert within.status_code == 200
    across = writer.patch(f"{base}/m2", json={"folder_ids": ["f_priv"]})
    assert across.status_code == 403
    assert "outside the folders of the grants" in across.json()["error"]["message"]
    assert writer.patch(f"{base}/m0", json={"unread": False}).status_code == 404


def test_to_the_trash_from_the_folders_but_not_read_there(
    app_client: TestClient, services: Services, mailbox: str
) -> None:
    writer = caller(
        app_client, services, mailbox, (["mail.read", "mail.write"], ["Invoices"])
    )
    base = f"/v1/accounts/{mailbox}/messages"
    assert writer.delete(f"{base}/m1").status_code == 204
    assert writer.get(f"{base}/m1").status_code == 404
    assert writer.delete(f"{base}/m3").status_code == 404
    reader = caller(
        app_client, services, mailbox, (["mail.read"], ["Invoices", "trash"])
    )
    assert reader.get(f"{base}/m1").status_code == 200


def test_deleting_for_good_keeps_to_the_folders(
    app_client: TestClient, services: Services, mailbox: str
) -> None:
    deleter = caller(app_client, services, mailbox, (["mail.delete"], ["Invoices"]))
    base = f"/v1/accounts/{mailbox}/messages"
    assert deleter.delete(f"{base}/m3", params={"permanent": True}).status_code == 404
    assert deleter.delete(f"{base}/m2", params={"permanent": True}).status_code == 204


def test_a_batch_refuses_each_message_out_of_reach(
    app_client: TestClient, services: Services, mailbox: str
) -> None:
    writer = caller(app_client, services, mailbox, (["mail.write"], ["Invoices"]))
    answer = writer.post(
        f"/v1/accounts/{mailbox}/messages/batch",
        json={"ids": ["m1", "m3"], "action": "update", "changes": {"unread": True}},
    ).json()
    outcome = {r["id"]: r for r in answer["results"]}
    assert outcome["m1"]["ok"] is True
    assert outcome["m3"]["error"]["code"] == "not_found"
    memory = memory_of(services, mailbox)
    assert next(m for m in memory.messages if m.id == "m3").unread is False


def test_folders_are_made_and_moved_inside_the_folders(
    app_client: TestClient, services: Services, mailbox: str
) -> None:
    writer = caller(app_client, services, mailbox, (["mail.write"], ["Invoices"]))
    base = f"/v1/accounts/{mailbox}/folders"
    top = writer.post(base, json={"name": "Elsewhere"})
    assert top.status_code == 403
    inside = writer.post(base, json={"name": "2027", "parent_id": "f_inv"})
    assert inside.status_code == 201
    made = inside.json()["id"]
    assert (
        writer.post(base, json={"name": "x", "parent_id": "f_priv"}).status_code == 404
    )
    out = writer.patch(f"{base}/{made}", json={"parent_id": "f_priv"})
    assert out.status_code == 404
    assert writer.patch(f"{base}/f_priv", json={"name": "Mine"}).status_code == 404


# --- what is heard of -------------------------------------------------------------


def test_the_change_feed_keeps_to_the_folders(
    app_client: TestClient, client: TestClient, services: Services, mailbox: str
) -> None:
    reader = caller(app_client, services, mailbox, (["mail.read"], ["Invoices"]))
    url = f"/v1/accounts/{mailbox}/changes"
    state = reader.get(url).json()["state"]
    every = client.get("/v1/changes").json()["state"]
    base = f"/v1/accounts/{mailbox}/messages"
    for message in ("m1", "m3", "m0"):
        client.patch(f"{base}/{message}", json={"unread": True})
    heard = reader.get(url, params={"since": state}).json()
    assert [c["id"] for c in heard["changes"]] == ["m1"]
    assert "folder_id" not in heard["changes"][0]
    across = reader.get("/v1/changes", params={"since": every}).json()
    assert [c["id"] for c in across["changes"]] == ["m1"]
    # The admin hears of all three.
    seen = client.get(url, params={"since": state}).json()["changes"]
    assert [c["id"] for c in seen] == ["m1", "m3", "m0"]


def test_a_reply_needs_the_original_in_reach(
    app_client: TestClient, services: Services, mailbox: str
) -> None:
    drafter = caller(
        app_client, services, mailbox, (["mail.read", "drafts"], ["Invoices"])
    )
    url = f"/v1/accounts/{mailbox}/drafts"

    def reply_to(message: str) -> int:
        draft = {"reference": {"message_id": message, "action": "reply"}, "text": "x"}
        return drafter.post(url, json=draft).status_code

    assert reply_to("m3") == 404
    assert reply_to("m1") == 201


def test_folders_need_at_least_one_name(client: TestClient, mailbox: str) -> None:
    grant = {"accounts": [mailbox], "allow": ["mail.read"], "folders": []}
    made = client.post("/v1/users", json={"name": "x", "grants": [grant]})
    assert made.status_code == 422


# --- the parts ---------------------------------------------------------------------


def test_reach_takes_in_subfolders_and_holds_per_grant() -> None:
    folders = [
        Folder(id="inbox", name="INBOX", role=FolderRole.INBOX),
        INVOICES,
        YEAR,
        Folder(id="f_deep", name="Q1", parent_id="f_2026"),
        PRIVATE,
    ]
    reach = Reach([frozenset({"Invoices"}), frozenset({"inbox"})], folders)
    assert reach.ids == {"f_inv", "f_2026", "f_deep", "inbox"}
    assert reach.holds("f_inv", "f_deep")
    assert not reach.holds("f_inv", "inbox")
    assert reach.sees(["f_priv", "f_deep"]) and not reach.sees(["f_priv"])


def test_access_names_the_folders_of_each_grant() -> None:
    narrowed = Grant(accounts=["a"], allow=["mail.read", "send"], folders=["x"])
    access = Access("u", "u", [narrowed])
    assert access.folder_scopes("get_message", "a") == [frozenset({"x"})]
    # Sending is not about folders.
    assert access.folder_scopes("send_message", "a") is None
    wide = Access("u", "u", [narrowed, Grant(accounts=["*"], allow=["get_message"])])
    assert wide.folder_scopes("get_message", "a") is None
    assert wide.folder_scopes("list_messages", "a") == [frozenset({"x"})]


def test_folders_are_handed_out_no_wider() -> None:
    access = Access(
        "u", "u", [Grant(accounts=["a"], allow=["mail.read"], folders=["x", "y"])]
    )
    assert access.covers([Grant(accounts=["a"], allow=["mail.read"], folders=["x"])])
    assert not access.covers(
        [Grant(accounts=["a"], allow=["mail.read"], folders=["z"])]
    )
    assert not access.covers([Grant(accounts=["a"], allow=["mail.read"])])


def test_the_inbox_reaches_its_own_subfolders() -> None:
    """A folder someone made below the inbox, as Outlook allows on
    Microsoft accounts, goes with it."""
    inbox = Folder(id="inbox", name="Inbox", role=FolderRole.INBOX)
    bills = Folder(id="f_bills", name="Bills", parent_id="inbox")
    sent = Folder(id="sent", name="Sent", role=FolderRole.SENT)
    reach = Reach([frozenset({"inbox"})], [inbox, bills, sent])
    assert reach.ids == {"inbox", "f_bills"}


def test_what_a_narrowed_reader_hears_of() -> None:
    reach = Reach([frozenset({"Invoices"})], [INVOICES, PRIVATE])

    def heard(kind: str, folder: str | None) -> bool:
        record = ChangeRecord(
            type=kind,  # type: ignore[arg-type]
            id="x",
            account_id="a",
            at=datetime(2026, 10, 5, tzinfo=UTC),
            folder_id=folder,
        )
        return reach.hears(record)

    assert heard("message.updated", "f_inv")
    assert not heard("message.updated", "f_priv")
    # A deletion of unknown place names an id alone, a change of unknown
    # place more: only the first is heard of.
    assert heard("message.deleted", None)
    assert not heard("message.created", None)
    assert heard("account.needs_reauth", None)
