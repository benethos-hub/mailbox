"""Attachments of other messages in a message to send or a draft
(``attachments_from``): fetched, attached before the message's own, and
only from mail the caller may read."""

from __future__ import annotations

from email import message_from_bytes
from email.policy import default
from typing import Any

import pytest
from fastapi.testclient import TestClient

from benethos_mailbox_service.assembly import Services
from benethos_mailbox_service.data.models import Attachment, Grant
from benethos_mailbox_service.domain.mailbox import checks

from ...conftest import bearer_for, memory_of

INVOICE = {"message_id": "m0", "attachment_id": "att_0"}


@pytest.fixture
def invoice(services: Services, account_id: str) -> str:
    """m0 carries invoice.pdf."""
    memory = memory_of(services, account_id)
    memory.messages[0].attachments.append(
        Attachment(
            id="att_0", filename="invoice.pdf", content_type="application/pdf", size=4
        )
    )
    memory.attachment_data[("m0", "att_0")] = b"%PDF"
    return account_id


def body(**fields: Any) -> dict[str, Any]:
    return {
        "to": [{"email": "you@example.com"}],
        "subject": "The invoice",
        "text": "Attached.",
        "attachments_from": [INVOICE],
        **fields,
    }


def files(raw: bytes) -> list[tuple[str | None, str, bytes]]:
    mail = message_from_bytes(raw, policy=default)
    return [
        (a.get_filename(), a.get_content_type(), a.get_payload(decode=True))
        for a in mail.iter_attachments()
    ]


def test_sent_with_an_attachment_of_another_message(
    client: TestClient, services: Services, invoice: str
) -> None:
    own = {"filename": "note.txt", "content_type": "text/plain", "data": "eA=="}
    answer = client.post(f"/v1/accounts/{invoice}/send", json=body(attachments=[own]))
    assert answer.status_code == 200, answer.text
    [(_, _, raw)] = memory_of(services, invoice).outbox
    assert files(raw) == [
        ("invoice.pdf", "application/pdf", b"%PDF"),
        ("note.txt", "text/plain", b"x"),
    ]


def test_a_draft_takes_them_as_well(client: TestClient, invoice: str) -> None:
    created = client.post(f"/v1/accounts/{invoice}/drafts", json=body())
    assert created.status_code == 201, created.text
    draft = client.get(f"/v1/accounts/{invoice}/messages/{created.json()['id']}")
    assert [a["filename"] for a in draft.json()["attachments"]] == ["invoice.pdf"]
    # Sent back as it is stored, the draft is left alone. With a source it
    # is composed anew.
    replaced = client.put(
        f"/v1/accounts/{invoice}/drafts/{created.json()['id']}", json=body()
    )
    assert replaced.status_code == 200
    again = client.get(f"/v1/accounts/{invoice}/messages/{replaced.json()['id']}")
    assert [a["filename"] for a in again.json()["attachments"]] == ["invoice.pdf"]


def test_only_who_may_read_the_mail(
    app_client: TestClient, services: Services, invoice: str
) -> None:
    sender = bearer_for(services, Grant(accounts=[invoice], allow=["send"]))
    url = f"/v1/accounts/{invoice}/send"
    answer = app_client.post(url, json=body(), headers=sender)
    assert answer.status_code == 403
    assert not memory_of(services, invoice).outbox
    reader = bearer_for(
        services, Grant(accounts=[invoice], allow=["send", "mail.read"])
    )
    assert app_client.post(url, json=body(), headers=reader).status_code == 200


def test_only_from_folders_the_grants_reach(
    app_client: TestClient, services: Services, invoice: str
) -> None:
    """m0 is in the inbox, the grant reaches the sent folder alone."""
    narrow = bearer_for(
        services,
        Grant(accounts=[invoice], allow=["send", "mail.read"], folders=["Sent"]),
    )
    answer = app_client.post(
        f"/v1/accounts/{invoice}/send", json=body(), headers=narrow
    )
    assert answer.status_code == 404
    assert not memory_of(services, invoice).outbox


def test_an_attachment_not_there(client: TestClient, invoice: str) -> None:
    gone = body(attachments_from=[{**INVOICE, "attachment_id": "att_9"}])
    assert client.post(f"/v1/accounts/{invoice}/send", json=gone).status_code == 404


def test_they_count_toward_the_size_limit(
    client: TestClient, invoice: str, monkeypatch: pytest.MonkeyPatch
) -> None:
    monkeypatch.setattr(checks, "MAX_ATTACHMENT_BYTES", 3)
    answer = client.post(f"/v1/accounts/{invoice}/send", json=body())
    assert answer.status_code == 400
    assert "the attachments exceed" in answer.json()["error"]["message"]
