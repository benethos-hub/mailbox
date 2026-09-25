"""Writing in the configuration UI: flags, moving, deleting, folders,
composing, drafts and sending."""

from __future__ import annotations

import html
import re
from email import message_from_bytes

from fastapi.testclient import TestClient

from benethos_mailbox_api.data.models import Folder, FolderRole, Grant
from benethos_mailbox_api.data.providers import MemoryProvider
from benethos_mailbox_api.main import Services

from .conftest import bearer_for
from .ui_helpers import csrf_of, post, sign_in


def _adapter(services: Services, account_id: str) -> MemoryProvider:
    adapter = services.adapters.get(account_id)
    assert isinstance(adapter, MemoryProvider)
    return adapter


def _with_trash(services: Services, account_id: str) -> MemoryProvider:
    adapter = _adapter(services, account_id)
    adapter.folders.append(Folder(id="trash", name="Trash", role=FolderRole.TRASH))
    adapter.folders.append(Folder(id="archive", name="Archive"))
    return adapter


# --- one message ----------------------------------------------------------------------


def test_flags_on_a_message(
    ui: TestClient, services: Services, account_id: str
) -> None:
    adapter = _adapter(services, account_id)
    url = f"/ui/accounts/{account_id}/mail/m3"
    page = ui.get(url).text
    assert "Mark unread" in page and "Star" in page
    post(ui, f"{url}/flags", {"unread": "1"})
    post(ui, f"{url}/flags", {"starred": "1"})
    message = next(m for m in adapter.messages if m.id == "m3")
    assert message.unread and message.starred
    assert "Unstar" in ui.get(url).text


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
    headers = bearer_for(services, Grant(accounts=[account_id], allow=["mail.read"]))
    sign_in(app_client, headers["Authorization"].removeprefix("Bearer "))
    page = app_client.get(f"/ui/accounts/{account_id}/mail/m1").text
    assert "Mark unread" not in page and "Reply" not in page and "Move" not in page
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
    none = post(ui, url, {"action": "read"}, follow_redirects=False)
    assert "Tick+at+least+one" in none.headers["location"]
    unknown = post(ui, url, {"ids": "m1", "action": "explode"}, follow_redirects=False)
    assert "Choose+an+action" in unknown.headers["location"]
    nowhere = post(ui, url, {"ids": "m1", "action": "move"}, follow_redirects=False)
    assert "Choose+a+folder" in nowhere.headers["location"]


# --- folders --------------------------------------------------------------------------


def test_create_rename_move_and_delete_a_folder(
    ui: TestClient, services: Services, account_id: str
) -> None:
    adapter = _adapter(services, account_id)
    base = f"/ui/accounts/{account_id}/folders"
    created = post(ui, base, {"name": "Projects"})
    assert "Projects created." in created.text
    [folder] = [f for f in adapter.folders if f.name == "Projects"]
    assert "This folder" in created.text
    renamed = post(ui, f"{base}/rename", {"folder": folder.id, "name": "Work"})
    assert "Renamed." in renamed.text
    [work] = [f for f in adapter.folders if f.name == "Work"]
    inner = post(ui, base, {"name": "Inner", "parent": work.id})
    [child] = [f for f in adapter.folders if f.name == "Inner"]
    assert child.parent_id == work.id and "Inner created." in inner.text
    post(ui, f"{base}/move", {"folder": child.id, "parent": ""})
    assert next(f for f in adapter.folders if f.name == "Inner").parent_id is None
    refused = post(ui, f"{base}/delete", {"folder": "inbox"})
    assert "inbox" in refused.text.lower() and "err" not in refused.url.path
    deleted = post(ui, f"{base}/delete", {"folder": work.id})
    assert "Folder deleted." in deleted.text


def test_a_bad_folder_name_is_named(ui: TestClient, account_id: str) -> None:
    answer = post(
        ui,
        f"/ui/accounts/{account_id}/folders",
        {"name": "a*b"},
        follow_redirects=False,
    )
    assert "without" in answer.headers["location"]


# --- composing and sending ------------------------------------------------------------


def test_send_a_new_message(
    ui: TestClient, services: Services, account_id: str
) -> None:
    adapter = _adapter(services, account_id)
    form = ui.get(f"/ui/accounts/{account_id}/compose").text
    key = re.search(r'name="idempotency_key" value="([^"]+)"', form)
    assert key is not None
    fields = {
        "csrf_token": csrf_of(form),
        "idempotency_key": key.group(1),
        "to": "Bob <bob@example.org>, carol@example.org",
        "subject": "Hello",
        "text": "Hi there",
        "do": "send",
    }
    sent = ui.post(
        f"/ui/accounts/{account_id}/compose",
        data=fields,
        files=[("attachments", ("note.txt", b"note", "text/plain"))],
    )
    assert "Sent." in sent.text
    [(_, recipients, raw)] = adapter.outbox
    assert recipients == ["bob@example.org", "carol@example.org"]
    parsed = message_from_bytes(raw)
    assert parsed["Subject"] == "Hello"
    assert [p.get_filename() for p in parsed.walk() if p.get_filename()] == ["note.txt"]
    # The same form sent again is the same send.
    again = ui.post(
        f"/ui/accounts/{account_id}/compose",
        data=fields,
        files=[("attachments", ("note.txt", b"note", "text/plain"))],
    )
    assert "Sent." in again.text
    assert len(adapter.outbox) == 1


def test_a_failed_send_keeps_what_was_typed(
    ui: TestClient, services: Services, account_id: str
) -> None:
    answer = post(
        ui,
        f"/ui/accounts/{account_id}/compose",
        {
            "to": "not an address",
            "subject": "Keep",
            "text": "my long text",
            "do": "send",
        },
    )
    assert answer.status_code == 400
    assert "a message needs at least one recipient" in answer.text or (
        "not an address" in answer.text
    )
    assert "my long text" in answer.text and 'value="Keep"' in answer.text
    assert _adapter(services, account_id).outbox == []


def test_a_bad_address_is_named(ui: TestClient, account_id: str) -> None:
    answer = post(
        ui,
        f"/ui/accounts/{account_id}/compose",
        {"to": "bob@", "text": "x", "do": "send"},
    )
    assert answer.status_code == 400 and "To: bob@ is not an address" in answer.text


def test_reply_quotes_and_finds_the_recipient(
    ui: TestClient, services: Services, account_id: str
) -> None:
    adapter = _adapter(services, account_id)
    page = ui.get(
        f"/ui/accounts/{account_id}/compose",
        params={"original": "m1", "action": "reply"},
    ).text
    assert "Reply: Invoice 1" in page and 'name="original" value="m1"' in page
    sent = post(
        ui,
        f"/ui/accounts/{account_id}/compose",
        {"original": "m1", "action": "reply", "text": "Thanks", "do": "send"},
    )
    assert "Sent." in sent.text
    [(_, recipients, raw)] = adapter.outbox
    assert recipients == ["alice@example.com"]
    assert message_from_bytes(raw)["Subject"] == "Re: Invoice 1"
    assert "$answered" in next(m for m in adapter.messages if m.id == "m1").keywords


def test_drafts_save_edit_send(
    ui: TestClient, services: Services, account_id: str
) -> None:
    adapter = _adapter(services, account_id)
    saved = post(
        ui,
        f"/ui/accounts/{account_id}/compose",
        {"to": "bob@example.org", "subject": "Plan", "text": "first", "do": "save"},
    )
    assert "Draft saved." in saved.text
    draft_url = saved.url.path
    assert re.fullmatch(rf"/ui/accounts/{account_id}/drafts/[^/]+", draft_url)
    assert 'value="bob@example.org"' in saved.text and "first" in saved.text
    listed = ui.get(f"/ui/accounts/{account_id}/drafts").text
    assert f'href="{draft_url}"' in listed
    edited = post(
        ui,
        draft_url,
        {"to": "bob@example.org", "subject": "Plan", "text": "second", "do": "save"},
    )
    assert "Draft saved." in edited.text and "second" in edited.text
    assert adapter.outbox == []
    sent = post(
        ui,
        draft_url,
        {"to": "bob@example.org", "subject": "Plan", "text": "second", "do": "send"},
    )
    assert "Sent." in sent.text
    [(_, recipients, raw)] = adapter.outbox
    assert recipients == ["bob@example.org"]
    assert "second" in message_from_bytes(raw).get_payload()
    assert ui.get(draft_url).status_code == 404


def test_delete_a_draft(ui: TestClient, account_id: str) -> None:
    saved = post(
        ui,
        f"/ui/accounts/{account_id}/compose",
        {"subject": "Throwaway", "do": "save"},
    )
    deleted = post(ui, saved.url.path, {"do": "delete"})
    assert "Draft deleted." in deleted.text
    assert "Throwaway" not in deleted.text


def test_saving_a_draft_keeps_its_attachments(
    ui: TestClient, services: Services, account_id: str
) -> None:
    page = ui.get(f"/ui/accounts/{account_id}/compose").text
    saved = ui.post(
        f"/ui/accounts/{account_id}/compose",
        data={"csrf_token": csrf_of(page), "subject": "With file", "do": "save"},
        files=[("attachments", ("plan.txt", b"plan", "text/plain"))],
    )
    assert "plan.txt" in saved.text
    again = post(ui, saved.url.path, {"subject": "With file, changed", "do": "save"})
    assert "plan.txt" in again.text
    attachment = re.search(r'name="drop" value="([^"]+)"', again.text)
    assert attachment is not None
    dropped = post(
        ui,
        saved.url.path,
        {"subject": "With file, changed", "drop": attachment.group(1), "do": "save"},
    )
    assert "plan.txt" not in dropped.text


def test_sending_needs_its_right(
    app_client: TestClient, services: Services, account_id: str
) -> None:
    headers = bearer_for(
        services, Grant(accounts=[account_id], allow=["mail.read", "drafts"])
    )
    sign_in(app_client, headers["Authorization"].removeprefix("Bearer "))
    form = app_client.get(f"/ui/accounts/{account_id}/compose").text
    assert "Save as draft" in form and ">Send<" not in form
    refused = post(
        app_client,
        f"/ui/accounts/{account_id}/compose",
        {"to": "bob@example.org", "text": "x", "do": "send"},
    )
    assert refused.status_code == 403 and "missing right" in refused.text
    assert _adapter(services, account_id).outbox == []


def test_a_grant_that_narrows_recipients_is_shown(
    app_client: TestClient, services: Services, account_id: str
) -> None:
    headers = bearer_for(
        services,
        Grant(
            accounts=[account_id],
            allow=["mail.read", "send"],
            recipients=["*@example.org"],
        ),
    )
    sign_in(app_client, headers["Authorization"].removeprefix("Bearer "))
    refused = post(
        app_client,
        f"/ui/accounts/{account_id}/compose",
        {"to": "eve@elsewhere.example", "text": "x", "do": "send"},
    )
    assert refused.status_code == 403
    assert "eve@elsewhere.example" in refused.text
    assert _adapter(services, account_id).outbox == []


def test_a_changed_reply_draft_stays_in_its_thread(
    ui: TestClient, services: Services, account_id: str
) -> None:
    adapter = _adapter(services, account_id)
    saved = post(
        ui,
        f"/ui/accounts/{account_id}/compose",
        {"original": "m1", "action": "reply", "text": "First", "do": "save"},
    )
    assert "Reply: Invoice 1" in saved.text and "stays linked" in saved.text
    text = re.search(r'name="text" rows="14">([^<]*)</textarea>', saved.text)
    to = re.search(r'name="to" value="([^"]*)"', saved.text)
    assert text is not None and to is not None
    body = html.unescape(text.group(1)).replace("First", "Second", 1)
    fields = {
        "to": html.unescape(to.group(1)),
        "subject": "Re: Invoice 1",
        "text": body,
    }
    edited = post(ui, saved.url.path, {**fields, "do": "save"})
    assert "Draft saved." in edited.text
    assert html.unescape(edited.text).count("> body 1") == 1
    sent = post(ui, saved.url.path, {**fields, "do": "send"})
    assert "Sent." in sent.text
    [(_, recipients, raw)] = adapter.outbox
    assert recipients == ["alice@example.com"]
    assert "Second" in message_from_bytes(raw).get_payload()
    assert "$answered" in next(m for m in adapter.messages if m.id == "m1").keywords
