"""Changing a message: unread, starred and keywords (CONCEPT 6.3)."""

from __future__ import annotations

import pytest
from fastapi.testclient import TestClient
from pydantic import ValidationError

from benethos_mailbox_service.assembly import Services
from benethos_mailbox_service.data.models import Grant, MessageUpdate
from benethos_mailbox_service.data.providers.imap import mappers
from benethos_mailbox_service.errors import (
    NotFoundError,
    NotSupportedError,
)

from ...conftest import bearer_for
from ...data.providers.test_imap import provider
from ...imap_fake import FakeMailBox
from ...provider_ops import update

ANY_KEYWORD = frozenset({"\\Seen", "\\Flagged", "\\*"})

# --- flags and keywords, pure ---------------------------------------------


def test_keywords_of_flags() -> None:
    flags = ("\\Seen", "\\Answered", "\\Flagged", "$Forwarded", "Work", "\\Recent")
    assert mappers.keywords(flags) == ["$answered", "$forwarded", "work"]


def test_flag_changes() -> None:
    add, remove = mappers.flag_changes(
        ("\\Seen", "$Forwarded", "Work"),
        MessageUpdate(unread=True, starred=True, keywords=["$forwarded", "$junk"]),
        ANY_KEYWORD,
    )
    assert add == ["\\Flagged", "$Junk"]
    # Removed as the server spells it.
    assert remove == ["\\Seen", "Work"]


def test_setting_answered_is_a_system_flag() -> None:
    add, _ = mappers.flag_changes(
        (), MessageUpdate(keywords=["$answered"]), frozenset()
    )
    assert add == ["\\Answered"]


def test_nothing_to_change() -> None:
    assert mappers.flag_changes(("\\Seen",), MessageUpdate(), ANY_KEYWORD) == ([], [])


@pytest.mark.parametrize("keyword", ["$seen", "$Flagged", "$deleted"])
def test_keywords_that_bypass_fields_are_refused(keyword: str) -> None:
    """Refused for every provider, at the boundary."""
    with pytest.raises(ValidationError, match="use unread"):
        MessageUpdate(keywords=[keyword])


def test_new_keywords_need_a_server_that_keeps_them() -> None:
    with pytest.raises(NotSupportedError):
        mappers.flag_changes(
            (), MessageUpdate(keywords=["work"]), frozenset({"\\Seen"})
        )
    # Kept: the server keeps any flag, lists this one, or said nothing.
    for permanent in ({"\\*"}, {"\\Seen", "Work"}, set()):
        add, _ = mappers.flag_changes(
            (), MessageUpdate(keywords=["work"]), frozenset(permanent)
        )
        assert add == ["work"]


def test_keywords_added_and_taken_off() -> None:
    add, remove = mappers.flag_changes(
        ("\\Seen", "$Forwarded", "Work"),
        MessageUpdate(add_keywords=["work", "Urgent"], remove_keywords=["$forwarded"]),
        ANY_KEYWORD,
    )
    # One it has already is not added again, whatever its case.
    assert add == ["Urgent"]
    assert remove == ["$Forwarded"]


@pytest.mark.parametrize(
    "fields",
    [
        {"keywords": ["a"], "add_keywords": ["b"]},
        {"keywords": [], "remove_keywords": ["b"]},
        {"folder_ids": ["inbox"], "add_folder_ids": ["f1"]},
        {"folder_ids": ["inbox"], "remove_folder_ids": ["f1"]},
        {"add_keywords": ["Work"], "remove_keywords": ["work"]},
        {"add_folder_ids": ["f1"], "remove_folder_ids": ["f1"]},
        {"add_keywords": ["$seen"]},
        {"remove_keywords": ["$flagged"]},
    ],
)
def test_a_list_is_replaced_or_changed_not_both(fields: dict[str, list[str]]) -> None:
    with pytest.raises(ValidationError):
        MessageUpdate.model_validate(fields)


def test_what_a_message_has_once_changed() -> None:
    change = MessageUpdate(add_keywords=["Work"], remove_keywords=["$junk"])
    assert change.keywords_after(["$junk", "$answered"]) == {"$answered", "work"}
    assert change.folders_after(["inbox"]) is None
    labels = MessageUpdate(add_folder_ids=["f2", "f1"], remove_folder_ids=["inbox"])
    assert labels.folders_after(["inbox", "f1"]) == ["f1", "f2"]
    assert labels.keywords_after(["work"]) is None
    assert labels.named_folders() == ["f2", "f1", "inbox"]
    assert MessageUpdate(folder_ids=["a", "a"]).folders_after(["b"]) == ["a"]
    assert MessageUpdate(keywords=["Work"]).keywords_after(["x"]) == {"work"}


@pytest.mark.parametrize("keyword", ["two words", "\\Seen", "a(b", "", "x" * 101])
def test_invalid_keywords_are_refused(keyword: str) -> None:
    with pytest.raises(ValueError):
        MessageUpdate(keywords=[keyword])


# --- the IMAP adapter -----------------------------------------------------


async def test_update_on_the_server(server: FakeMailBox) -> None:
    imap = provider(server)
    message_id = mappers.message_id("INBOX", 7, 3)
    summary = await update(
        imap,
        message_id,
        MessageUpdate(unread=False, starred=True, keywords=["$forwarded"]),
    )
    assert summary.id == message_id
    assert (summary.unread, summary.starred) == (False, True)
    assert summary.keywords == ["$forwarded"]
    assert set(server.folders["INBOX"].messages[3][1]) == {
        "\\Seen",
        "\\Flagged",
        "$Forwarded",
    }
    # Written in a folder selected read-write, then read back without \Seen.
    assert ("select", "INBOX", False) in server.calls
    assert server.calls[-1][2] == "header"


async def test_keywords_added_on_the_server_keep_the_others(
    server: FakeMailBox,
) -> None:
    imap = provider(server)
    message_id = mappers.message_id("INBOX", 7, 3)
    await update(imap, message_id, MessageUpdate(keywords=["$forwarded", "work"]))
    summary = await update(
        imap,
        message_id,
        MessageUpdate(add_keywords=["Urgent"], remove_keywords=["$forwarded"]),
    )
    assert summary.keywords == ["urgent", "work"]
    assert set(server.folders["INBOX"].messages[3][1]) == {"Urgent", "work"}


async def test_an_empty_update_writes_nothing(server: FakeMailBox) -> None:
    imap = provider(server)
    summary = await update(imap, mappers.message_id("INBOX", 7, 3), MessageUpdate())
    assert summary.unread is True
    assert not any(c[0] == "store" for c in server.calls)


@pytest.mark.parametrize(
    "message_id",
    [mappers.message_id("INBOX", 7, 99), mappers.message_id("INBOX", 6, 3)],
)
async def test_update_of_an_unknown_message(
    server: FakeMailBox,
    message_id: str,
) -> None:
    with pytest.raises(NotFoundError):
        await update(provider(server), message_id, MessageUpdate(starred=True))


# --- the API ---------------------------------------------------------


def test_patch_a_message(client: TestClient, account_id: str) -> None:
    answer = client.patch(
        f"/v1/accounts/{account_id}/messages/m0",
        json={"unread": False, "keywords": ["$forwarded"]},
    )
    assert answer.status_code == 200
    body = answer.json()
    assert (body["id"], body["account_id"]) == ("m0", account_id)
    assert (body["unread"], body["keywords"]) == (False, ["$forwarded"])
    again = client.get(f"/v1/accounts/{account_id}/messages/m0").json()
    assert again["unread"] is False


def test_patch_adds_and_takes_off_keywords(client: TestClient, account_id: str) -> None:
    url = f"/v1/accounts/{account_id}/messages/m0"
    client.patch(url, json={"keywords": ["work", "$junk"]})
    answer = client.patch(
        url, json={"add_keywords": ["Urgent"], "remove_keywords": ["$junk"]}
    )
    assert answer.status_code == 200
    assert answer.json()["keywords"] == ["urgent", "work"]
    mixed = client.patch(url, json={"keywords": ["a"], "add_keywords": ["b"]})
    assert mixed.status_code == 422


def test_patch_refuses_a_bad_keyword(client: TestClient, account_id: str) -> None:
    answer = client.patch(
        f"/v1/accounts/{account_id}/messages/m0", json={"keywords": ["two words"]}
    )
    assert answer.status_code == 422


def test_patch_needs_mail_write(
    app_client: TestClient, services: Services, account_id: str
) -> None:
    reader = bearer_for(services, Grant(accounts=[account_id], allow=["mail.read"]))
    answer = app_client.patch(
        f"/v1/accounts/{account_id}/messages/m0", json={"starred": True}, headers=reader
    )
    assert answer.status_code == 403
    writer = bearer_for(
        services, Grant(accounts=[account_id], allow=["mail.read", "mail.write"])
    )
    answer = app_client.patch(
        f"/v1/accounts/{account_id}/messages/m0", json={"starred": True}, headers=writer
    )
    assert answer.status_code == 200
