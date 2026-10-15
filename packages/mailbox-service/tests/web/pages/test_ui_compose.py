"""Composing in the configuration UI: new mail, replies, drafts and
sending."""

from __future__ import annotations

import html
import re
from email import message_from_bytes

import pytest
from fastapi.testclient import TestClient

from benethos_mailbox_common.log import redact
from benethos_mailbox_service.assembly import Services
from benethos_mailbox_service.data.models import Grant
from benethos_mailbox_service.data.providers.memory import MemoryProvider
from benethos_mailbox_service.errors import ProviderError

from ...conftest import browser_user, memory_of
from ...ui_helpers import csrf_of, post, sign_in


def test_send_a_new_message(
    ui: TestClient, services: Services, account_id: str
) -> None:
    adapter = memory_of(services, account_id)
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
    assert memory_of(services, account_id).outbox == []


def test_a_failed_send_shows_no_secret(
    ui: TestClient, account_id: str, monkeypatch: pytest.MonkeyPatch
) -> None:
    """A server's refusal may echo a credential: the page shows it redacted."""
    redact.note("s3cret-pw")

    async def refused(*args: object, **kwargs: object) -> None:
        raise ProviderError("the server said: s3cret-pw is wrong")

    monkeypatch.setattr(MemoryProvider, "send", refused)
    answer = post(
        ui,
        f"/ui/accounts/{account_id}/compose",
        {"to": "bob@example.com", "subject": "Hi", "text": "x", "do": "send"},
    )
    assert "the server said" in answer.text
    assert "s3cret-pw" not in answer.text


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
    adapter = memory_of(services, account_id)
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
    adapter = memory_of(services, account_id)
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
    sign_in(
        app_client,
        *browser_user(
            services, Grant(accounts=[account_id], allow=["mail.read", "drafts"])
        ),
    )
    form = app_client.get(f"/ui/accounts/{account_id}/compose").text
    assert "Save as draft" in form and ">Send<" not in form
    refused = post(
        app_client,
        f"/ui/accounts/{account_id}/compose",
        {"to": "bob@example.org", "text": "x", "do": "send"},
    )
    assert refused.status_code == 403 and "missing right" in refused.text
    assert memory_of(services, account_id).outbox == []


def test_a_grant_that_narrows_recipients_is_shown(
    app_client: TestClient, services: Services, account_id: str
) -> None:
    sign_in(
        app_client,
        *browser_user(
            services,
            Grant(
                accounts=[account_id],
                allow=["mail.read", "send"],
                recipients=["*@example.org"],
            ),
        ),
    )
    refused = post(
        app_client,
        f"/ui/accounts/{account_id}/compose",
        {"to": "eve@elsewhere.example", "text": "x", "do": "send"},
    )
    assert refused.status_code == 403
    assert "eve@elsewhere.example" in refused.text
    assert memory_of(services, account_id).outbox == []


def test_a_changed_reply_draft_stays_in_its_thread(
    ui: TestClient, services: Services, account_id: str
) -> None:
    adapter = memory_of(services, account_id)
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
