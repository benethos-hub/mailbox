"""Every kind of mailbox through the API, held to the same rules
(docs/UNIFORM.md section 7): an operation does what the neutral model
says where the account has the capability that guards it, and answers
`501 not_supported` where it lacks it. What falls short today is marked
as an expected failure with its place in UNIFORM.md, strictly: once it
is fixed, the mark has to go."""

from __future__ import annotations

import base64
from dataclasses import dataclass
from typing import Any

import pytest
from fastapi.testclient import TestClient

from benethos_mailbox_service.assembly import create_app
from benethos_mailbox_service.config import Settings

from ..conftest import admin_bearer
from ..mailboxes import ADDRESS, KINDS, Box, box, mail, services_of

PDF = b"%PDF-1.4 conformance"
# What UNIFORM.md names as work, where a test meets it.


def kinds(**known: str) -> list[Any]:
    """Every kind of mailbox, those named in ``known`` with the reason
    they fall short today."""
    return [
        pytest.param(k, marks=pytest.mark.xfail(reason=known[k], strict=True))
        if k in known
        else k
        for k in KINDS
    ]


@dataclass
class Account:
    client: TestClient
    base: str
    capabilities: set[str]
    marks: dict[str, list[str]]
    box: Box

    def find(self, subject: str, folder: str = "inbox") -> dict[str, Any]:
        """The summary of the mail with ``subject`` in ``folder``."""
        page = self.client.get(f"{self.base}/messages", params={"folder": folder})
        assert page.status_code == 200, page.text
        [found] = [m for m in page.json()["items"] if m["subject"] == subject]
        return found

    def has(self, capability: str) -> bool:
        return capability in self.capabilities


@pytest.fixture
def account(kind: str, monkeypatch: pytest.MonkeyPatch) -> Account:
    found = box(kind)
    services, account_id = services_of(found, monkeypatch)
    client = TestClient(
        create_app(Settings(storage="memory"), services), headers=admin_bearer(services)
    )
    base = f"/v1/accounts/{account_id}"
    described = client.get(base).json()
    return Account(
        client, base, set(described["capabilities"]), described["marks"], found
    )


def lacks(answer: Any) -> bool:
    """Whether ``answer`` is the one for a missing capability."""
    return bool(
        answer.status_code == 501 and answer.json()["error"]["code"] == "not_supported"
    )


# --- folders --------------------------------------------------------------------------


@pytest.mark.parametrize("kind", kinds())
def test_the_folders_name_one_inbox(account: Account) -> None:
    answer = account.client.get(f"{account.base}/folders")
    assert answer.status_code == 200
    roles = [f["role"] for f in answer.json()]
    assert roles.count("inbox") == 1


@pytest.mark.parametrize("kind", kinds())
def test_a_folder_is_made_renamed_and_removed(account: Account) -> None:
    made = account.client.post(f"{account.base}/folders", json={"name": "Projects"})
    if not account.has("folders"):
        assert lacks(made), made.text
        return
    assert made.status_code == 201, made.text
    folder_id = made.json()["id"]
    renamed = account.client.patch(
        f"{account.base}/folders/{folder_id}", json={"name": "Plans"}
    )
    assert renamed.status_code == 200, renamed.text
    assert renamed.json()["name"] == "Plans"
    # The answer names the folder: on IMAP the id follows the name
    # (UNIFORM 4.7, rule U4).
    folder_id = renamed.json()["id"]
    gone = account.client.delete(f"{account.base}/folders/{folder_id}")
    assert gone.status_code == 204, gone.text


# --- reading --------------------------------------------------------------------------


@pytest.mark.parametrize("kind", kinds())
def test_a_mail_reads_alike(account: Account) -> None:
    account.box.put(mail("Read me", text="Hello there"))
    summary = account.find("Read me")
    assert summary["from"]["email"] == "alice@example.com"
    if account.has("read_state"):
        # Without it the fields carry nothing (UNIFORM R5, decision 6.1).
        assert summary["unread"] is True and summary["starred"] is False
    assert not summary["has_attachments"]
    one = account.client.get(f"{account.base}/messages/{summary['id']}").json()
    assert one["subject"] == "Read me"
    assert (one["text_body"] or "").strip() == "Hello there"
    assert one["html_body"] is None
    assert one["message_id_header"] == "<Read.me@example.com>"
    assert [a["email"] for a in one["to"]] == [ADDRESS]
    raw = account.client.get(f"{account.base}/messages/{summary['id']}/raw")
    assert raw.status_code == 200 and b"Subject: Read me" in raw.content


@pytest.mark.parametrize("kind", kinds())
def test_a_file_reads_alike(account: Account) -> None:
    account.box.put(mail("With a file", file=PDF))
    summary = account.find("With a file")
    one = account.client.get(f"{account.base}/messages/{summary['id']}").json()
    assert one["has_attachments"] is True
    [file] = one["attachments"]
    assert (file["filename"], file["content_type"]) == ("offer.pdf", "application/pdf")
    data = account.client.get(
        f"{account.base}/messages/{summary['id']}/attachments/{file['id']}"
    )
    assert data.status_code == 200 and data.content == PDF


@pytest.mark.parametrize("kind", kinds())
def test_a_missing_message_is_not_found(account: Account) -> None:
    account.box.put(mail("Gone soon"))
    summary = account.find("Gone soon")
    url = f"{account.base}/messages/{summary['id']}"
    assert account.client.delete(url, params={"permanent": "true"}).status_code == 204
    answer = account.client.get(url)
    assert answer.status_code == 404, answer.text


@pytest.mark.parametrize("kind", kinds())
def test_a_list_pages_newest_first(account: Account) -> None:
    for n in (1, 2, 3):
        account.box.put(mail(f"Page {n}"))
    url = f"{account.base}/messages"
    first = account.client.get(url, params={"folder": "inbox", "limit": 2}).json()
    cursor = first["next_cursor"]
    assert len(first["items"]) == 2 and cursor
    rest = account.client.get(
        url, params={"folder": "inbox", "limit": 2, "cursor": cursor}
    ).json()
    subjects = [m["subject"] for m in first["items"] + rest["items"]]
    assert sorted(subjects) == ["Page 1", "Page 2", "Page 3"]


@pytest.mark.parametrize("kind", kinds())
def test_a_search_by_subject(account: Account) -> None:
    account.box.put(mail("Invoice March"))
    account.box.put(mail("Lunch"))
    answer = account.client.get(
        f"{account.base}/messages", params={"folder": "inbox", "subject": "invoice"}
    )
    if not account.has("search"):
        assert lacks(answer), answer.text
        return
    assert answer.status_code == 200, answer.text
    assert [m["subject"] for m in answer.json()["items"]] == ["Invoice March"]


# --- changing -------------------------------------------------------------------------


@pytest.mark.parametrize("kind", kinds())
def test_read_state_and_star(account: Account) -> None:
    account.box.put(mail("Mark me"))
    url = f"{account.base}/messages/{account.find('Mark me')['id']}"
    changed = account.client.patch(url, json={"unread": False, "starred": True})
    if not account.has("read_state") or not account.has("stars"):
        assert lacks(changed), changed.text
        return
    assert changed.status_code == 200, changed.text
    assert (changed.json()["unread"], changed.json()["starred"]) == (False, True)
    again = account.client.get(url).json()
    assert (again["unread"], again["starred"]) == (False, True)


@pytest.mark.parametrize("kind", kinds())
def test_a_keyword_added_and_taken_off(account: Account) -> None:
    account.box.put(mail("Tag me"))
    url = f"{account.base}/messages/{account.find('Tag me')['id']}"
    added = account.client.patch(url, json={"add_keywords": ["work"]})
    if not account.has("keywords"):
        assert lacks(added), added.text
        return
    assert added.status_code == 200, added.text
    assert "work" in added.json()["keywords"]
    taken = account.client.patch(url, json={"remove_keywords": ["work"]})
    assert taken.status_code == 200, taken.text
    assert "work" not in taken.json()["keywords"]


@pytest.mark.parametrize("kind", kinds())
def test_a_move_to_a_folder(account: Account) -> None:
    account.box.put(mail("Move me"))
    summary = account.find("Move me")
    url = f"{account.base}/messages/{summary['id']}"
    if not account.has("move"):
        moved = account.client.patch(url, json={"folder_ids": ["elsewhere"]})
        assert lacks(moved), moved.text
        return
    folder = account.client.post(f"{account.base}/folders", json={"name": "Kept"})
    folder_id = folder.json()["id"]
    moved = account.client.patch(url, json={"folder_ids": [folder_id]})
    assert moved.status_code == 200, moved.text
    # Gmail keeps every message in All Mail as well (UNIFORM 6, role `all`).
    assert folder_id in moved.json()["folder_ids"]
    assert summary["folder_ids"][0] not in moved.json()["folder_ids"]
    assert account.find("Move me", folder_id)["id"] == moved.json()["id"]


@pytest.mark.parametrize("kind", kinds())
def test_a_delete_puts_it_in_the_trash(account: Account) -> None:
    account.box.put(mail("Throw me"))
    url = f"{account.base}/messages/{account.find('Throw me')['id']}"
    trashed = account.client.delete(url)
    if not account.has("trash"):
        assert lacks(trashed), trashed.text
        return
    assert trashed.status_code == 204, trashed.text
    assert account.find("Throw me", "trash")


# --- drafts and sending ---------------------------------------------------------------


@pytest.mark.parametrize("kind", kinds())
def test_a_draft_is_written_replaced_and_removed(account: Account) -> None:
    drafts = f"{account.base}/drafts"
    made = account.client.post(
        drafts, json={"to": [{"email": "bob@example.com"}], "subject": "Plan"}
    )
    if not account.has("drafts"):
        assert lacks(made), made.text
        return
    assert made.status_code == 201, made.text
    listed = [d["id"] for d in account.client.get(drafts).json()["items"]]
    assert made.json()["id"] in listed
    replaced = account.client.put(
        f"{drafts}/{made.json()['id']}", json={"subject": "Plan", "text": "Later"}
    )
    assert replaced.status_code == 200, replaced.text
    new = replaced.json()["id"]
    assert [d["id"] for d in account.client.get(drafts).json()["items"]] == [new]
    gone = account.client.delete(f"{drafts}/{new}")
    assert gone.status_code == 204, gone.text
    assert account.client.get(drafts).json()["items"] == []


@pytest.mark.parametrize("kind", kinds())
def test_a_mail_is_sent(account: Account) -> None:
    sent = account.client.post(
        f"{account.base}/send",
        json={
            "to": [{"email": "bob@example.com"}],
            "subject": "Hi",
            "text": "Hello",
            "attachments": [
                {"filename": "offer.pdf", "data": base64.b64encode(PDF).decode()}
            ],
        },
    )
    if not account.has("send"):
        assert lacks(sent), sent.text
        return
    assert sent.status_code == 200, sent.text
    assert sent.json()["message_id_header"]


# --- threads --------------------------------------------------------------------------


@pytest.mark.parametrize("kind", kinds())
def test_a_mail_is_in_its_thread(account: Account) -> None:
    account.box.put(mail("Thread me"))
    summary = account.find("Thread me")
    if not account.has("threads"):
        answer = account.client.get(
            f"{account.base}/threads", params={"folder": "inbox"}
        )
        assert lacks(answer), answer.text
        return
    thread_id = summary["thread_id"]
    assert thread_id
    thread = account.client.get(f"{account.base}/threads/{thread_id}")
    assert thread.status_code == 200, thread.text
    assert summary["id"] in [m["id"] for m in thread.json()["messages"]]


@pytest.mark.parametrize("kind", kinds())
def test_a_mark_is_kept_or_lacks(account: Account) -> None:
    account.box.put(mail("Junk me"))
    url = f"{account.base}/messages/{account.find('Junk me')['id']}"
    marked = account.client.patch(url, json={"add_keywords": ["$junk"]})
    if "$junk" not in account.marks["written"]:
        assert lacks(marked), marked.text
        return
    assert marked.status_code == 200, marked.text
    assert "$junk" in marked.json()["keywords"]


@pytest.mark.parametrize("kind", kinds())
def test_what_lacks_is_refused_before_anything_changes(account: Account) -> None:
    """One change with something the account lacks changes nothing (R6)."""
    account.box.put(mail("Keep me"))
    url = f"{account.base}/messages/{account.find('Keep me')['id']}"
    lacking = next(
        (
            change
            for capability, change in (
                ("keywords", {"add_keywords": ["work"]}),
                ("move", {"folder_ids": ["inbox"]}),
            )
            if not account.has(capability)
        ),
        None,
    )
    if lacking is None or not account.has("stars"):
        return
    changed = account.client.patch(url, json={"starred": True, **lacking})
    assert lacks(changed), changed.text
    assert account.client.get(url).json()["starred"] is False


# --- what UNIFORM.md names as work ----------------------------------------------------


@pytest.mark.parametrize("kind", kinds())
def test_a_list_without_a_folder_is_the_inbox(account: Account) -> None:
    account.box.put(mail("In the inbox"))
    drafts = account.client.post(
        f"{account.base}/drafts", json={"subject": "Not in the inbox"}
    )
    listed = account.client.get(f"{account.base}/messages").json()["items"]
    subjects = [m["subject"] for m in listed]
    assert "In the inbox" in subjects
    if drafts.status_code == 201:
        assert "Not in the inbox" not in subjects


@pytest.mark.parametrize("kind", kinds())
def test_all_lists_every_folder_where_there_is_one(account: Account) -> None:
    """The role all: the server's own folder, or on IMAP and Microsoft one
    the adapter emulates. Without one it lacks (UNIFORM 6.5)."""
    account.box.put(mail("Everywhere"))
    folders = account.client.get(f"{account.base}/folders").json()
    there = any(f["role"] == "all" for f in folders)
    assert there == (account.box.kind in ("imap", "gmail", "microsoft"))
    answer = account.client.get(f"{account.base}/messages", params={"folder": "all"})
    if not there:
        assert lacks(answer)
        return
    assert answer.status_code == 200, answer.text
    assert "Everywhere" in [m["subject"] for m in answer.json()["items"]]


@pytest.mark.parametrize("kind", ["imap", "pop3"])
def test_a_send_without_smtp_lacks(kind: str, monkeypatch: pytest.MonkeyPatch) -> None:
    found = box(kind, smtp=False)
    services, account_id = services_of(found, monkeypatch)
    client = TestClient(
        create_app(Settings(storage="memory"), services), headers=admin_bearer(services)
    )
    assert "send" not in client.get(f"/v1/accounts/{account_id}").json()["capabilities"]
    sent = client.post(
        f"/v1/accounts/{account_id}/send",
        json={"to": [{"email": "bob@example.com"}], "subject": "Hi", "text": "Hello"},
    )
    assert lacks(sent), sent.text
