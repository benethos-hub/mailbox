"""Writing in the configuration UI: flags, moving, deleting and folders.
Composing and sending: ``test_ui_compose.py``."""

from __future__ import annotations

import html

from fastapi.testclient import TestClient

from benethos_mailbox_service.assembly import Services
from benethos_mailbox_service.data.models import Folder, FolderRole, Grant
from benethos_mailbox_service.data.providers.memory import MemoryProvider

from ...conftest import browser_user, memory_of, relearn
from ...ui_helpers import post, sign_in


def _with_trash(services: Services, account_id: str) -> MemoryProvider:
    adapter = memory_of(services, account_id)
    adapter.folders.append(Folder(id="trash", name="Trash", role=FolderRole.TRASH))
    adapter.folders.append(Folder(id="archive", name="Archive"))
    relearn(services, account_id)
    return adapter


# --- one message ----------------------------------------------------------------------


def test_flags_on_a_message(
    ui: TestClient, services: Services, account_id: str
) -> None:
    adapter = memory_of(services, account_id)
    url = f"/ui/accounts/{account_id}/mail/m3"
    page = ui.get(url).text
    assert "Mark unread" in page and "Star" in page
    post(ui, f"{url}/flags", {"unread": "1"})
    post(ui, f"{url}/flags", {"starred": "1"})
    message = next(m for m in adapter.messages if m.id == "m3")
    assert message.unread and message.starred
    assert "Unstar" in ui.get(url).text


def test_keywords_on_a_message(
    ui: TestClient, services: Services, account_id: str
) -> None:
    adapter = memory_of(services, account_id)

    def held() -> list[str]:
        return next(m for m in adapter.messages if m.id == "m3").keywords

    held().append("$answered")
    url = f"/ui/accounts/{account_id}/mail/m3"
    # A mark in its words, another keyword of the protocol by its name.
    held().append("$Important")
    flags = ui.get(url).text
    assert '<span class="tag">answered</span>' in flags
    assert '<span class="tag">Important</span>' in flags
    held().remove("$Important")
    post(ui, f"{url}/keywords", {"add": "  project-x "})
    post(ui, f"{url}/keywords", {"add": "later"})
    post(ui, f"{url}/keywords", {"add": "LATER"})  # held already
    assert held() == ["$answered", "later", "project-x"]
    page = ui.get(url).text
    assert 'aria-label="Remove the keyword project-x"' in page
    assert "Remove the keyword $answered" not in page
    post(ui, f"{url}/keywords", {"remove": "project-x"})
    assert held() == ["$answered", "later"]
    listing = ui.get(f"/ui/accounts/{account_id}/mail").text
    assert '<span class="tag">later</span>' in listing
    assert '<span class="tag">$answered</span>' not in listing
    for refused, reason in (
        ("$junk", "belong to the mail protocol"),
        ("\\Seen", "on one line"),
        ("", "Type a keyword."),
    ):
        answer = post(ui, f"{url}/keywords", {"add": refused})
        assert reason in html.unescape(answer.text), refused
    assert held() == ["$answered", "later"]


def test_move_trash_and_purge_a_message(
    ui: TestClient, services: Services, account_id: str
) -> None:
    adapter = _with_trash(services, account_id)
    url = f"/ui/accounts/{account_id}/mail/m2"
    moved = post(ui, f"{url}/move", {"folder": "archive"})
    assert "Moved." in moved.text
    assert next(m for m in adapter.messages if m.id == "m2").folder_ids == ["archive"]
    trashed = post(ui, f"{url}/delete", {"back": f"/ui/accounts/{account_id}/mail"})
    assert "Moved to the trash." in trashed.text
    page = ui.get(url).text
    assert "Move to the trash" not in page and "Delete for good" in page
    gone = post(
        ui, f"{url}/delete", {"permanent": "1", "back": "https://evil.example/"}
    )
    assert gone.url.path == f"/ui/accounts/{account_id}/mail"
    assert "Deleted for good." in gone.text
    assert all(m.id != "m2" for m in adapter.messages)


def test_a_reader_gets_no_buttons(
    app_client: TestClient, services: Services, account_id: str
) -> None:
    sign_in(
        app_client,
        *browser_user(services, Grant(accounts=[account_id], allow=["mail.read"])),
    )
    page = app_client.get(f"/ui/accounts/{account_id}/mail/m1").text
    assert "Mark unread" not in page and "Reply" not in page and "Move" not in page
    assert "New keyword" not in page
    listing = app_client.get(f"/ui/accounts/{account_id}/mail").text
    assert 'id="batch"' not in listing and "Write" not in listing
    refused = post(
        app_client, f"/ui/accounts/{account_id}/mail/m1/flags", {"unread": "1"}
    )
    assert "missing right" in refused.text


# --- many messages --------------------------------------------------------------------


def test_the_batch_menu(ui: TestClient, services: Services, account_id: str) -> None:
    adapter = _with_trash(services, account_id)
    listing = ui.get(f"/ui/accounts/{account_id}/mail").text
    assert 'id="batch"' in listing and 'form="batch"' in listing
    here = f"/ui/accounts/{account_id}/mail?folder=inbox"
    read = post(
        ui,
        f"/ui/accounts/{account_id}/mail/batch",
        {"ids": ["m0", "m1"], "action": "read", "back": here},
    )
    assert "2 done." in read.text
    assert not any(m.unread for m in adapter.messages if m.id in ("m0", "m1"))
    moved = post(
        ui,
        f"/ui/accounts/{account_id}/mail/batch",
        {"ids": ["m0", "nope"], "action": "move", "folder": "archive", "back": here},
    )
    assert "1 done." in moved.text and "1 failed" in moved.text
    purged = post(
        ui,
        f"/ui/accounts/{account_id}/mail/batch",
        {"ids": ["m0"], "action": "read", "purge": "1", "back": here},
    )
    assert "1 done." in purged.text
    assert all(m.id != "m0" for m in adapter.messages)


def test_the_batch_needs_ticks_and_an_action(ui: TestClient, account_id: str) -> None:
    url = f"/ui/accounts/{account_id}/mail/batch"
    none = post(ui, url, {"action": "read"})
    assert "Tick at least one" in none.text
    unknown = post(ui, url, {"ids": "m1", "action": "explode"})
    assert "Choose an action" in unknown.text
    nowhere = post(ui, url, {"ids": "m1", "action": "move"})
    assert "Choose a folder" in nowhere.text


# --- folders --------------------------------------------------------------------------


def test_create_rename_move_and_delete_a_folder(
    ui: TestClient, services: Services, account_id: str
) -> None:
    adapter = memory_of(services, account_id)
    base = f"/ui/accounts/{account_id}/folders"
    created = post(ui, base, {"name": "Projects"})
    assert "Projects created." in created.text
    [folder] = [f for f in adapter.folders if f.name == "Projects"]
    # The folder shown has its pencil and bin, its form folded.
    assert 'data-toggle="change-folder"' in created.text
    assert 'name="was_name" value="Projects"' in created.text
    renamed = post(
        ui,
        f"{base}/change",
        {"folder": folder.id, "was_name": "Projects", "name": "Work"},
    )
    assert "Renamed." in renamed.text
    [work] = [f for f in adapter.folders if f.name == "Work"]
    inner = post(ui, base, {"name": "Inner", "parent": work.id})
    [child] = [f for f in adapter.folders if f.name == "Inner"]
    assert child.parent_id == work.id and "Inner created." in inner.text
    # The form asks before a move: the select knows where it was.
    assert (
        f'data-was="{work.id}"' in inner.text
        and 'data-confirm-when="moved"' in inner.text
    )
    moved = post(
        ui,
        f"{base}/change",
        {
            "folder": child.id,
            "was_name": "Inner",
            "name": "Inner",
            "was_parent": work.id,
            "parent": "",
        },
    )
    assert "Moved." in moved.text
    assert next(f for f in adapter.folders if f.name == "Inner").parent_id is None
    same = post(
        ui, f"{base}/change", {"folder": child.id, "was_name": "Inner", "name": "Inner"}
    )
    assert "Nothing changed." in same.text
    refused = post(ui, f"{base}/delete", {"folder": "inbox"})
    assert "inbox" in refused.text.lower() and "err" not in refused.url.path
    deleted = post(ui, f"{base}/delete", {"folder": work.id})
    assert "Folder deleted." in deleted.text


def test_a_bad_folder_name_is_named(
    ui: TestClient, services: Services, account_id: str
) -> None:
    _with_trash(services, account_id)
    answer = post(
        ui,
        f"/ui/accounts/{account_id}/folders",
        {"name": "a*b", "shown": "archive", "parent": "archive"},
    )
    assert answer.status_code == 400
    assert 'class="notice err"' in answer.text
    assert "without" in answer.text
    # The page of the folder the form was on, with what was typed.
    assert 'name="name" value="a*b"' in answer.text
    # The form at the head of the folders is open again, with its choice.
    assert '<div class="row-form open" id="new-folder">' in answer.text
    assert '<option value="archive" selected>' in answer.text


def test_a_refused_rename_or_move_keeps_what_was_typed(
    ui: TestClient, services: Services, account_id: str
) -> None:
    adapter = _with_trash(services, account_id)
    base = f"/ui/accounts/{account_id}/folders"
    renamed = post(
        ui,
        f"{base}/change",
        {"folder": "archive", "was_name": "Archive", "name": "Old%"},
    )
    assert renamed.status_code == 400
    assert 'id="f-folder-name" name="name" value="Old%"' in renamed.text
    assert '<div class="row-form open" id="change-folder">' in renamed.text
    moved = post(
        ui,
        f"{base}/change",
        {
            "folder": "archive",
            "was_name": "Archive",
            "name": "Archive",
            "parent": "nowhere",
        },
    )
    assert moved.status_code == 400 and 'id="change-folder"' in moved.text
    assert [f.name for f in adapter.folders].count("Archive") == 1
