"""Drafts (CONCEPT 6.4): sending a draft."""

from __future__ import annotations

from email import message_from_bytes

from fastapi.testclient import TestClient

from benethos_mailbox_service.assembly import Services
from benethos_mailbox_service.data.mail import compose
from benethos_mailbox_service.data.models import (
    Grant,
)

from ...conftest import bearer_for, memory_of
from .test_drafts import drafts_url

# --- sending a draft ----------------------------------------------------------------


def test_a_sent_draft_goes_out_as_stored_and_is_gone(
    client: TestClient, services: Services, account_id: str
) -> None:
    draft = client.post(
        drafts_url(account_id),
        json={
            "to": [{"email": "bob@example.com"}],
            "bcc": [{"email": "carol@example.com"}],
            "subject": "Plan",
            "text": "Ready.",
        },
    ).json()
    sent = client.post(f"{drafts_url(account_id, draft['id'])}/send")
    assert sent.status_code == 200
    result = sent.json()
    assert result["sent_copy_id"]

    [(sender, recipients, raw)] = memory_of(services, account_id).outbox
    assert sender == "me@example.com"
    assert recipients == ["bob@example.com", "carol@example.com"]
    out = message_from_bytes(raw)
    assert out["Bcc"] is None and out[compose.REFERENCE_HEADER] is None
    assert out["Message-ID"] == result["message_id_header"]

    assert client.get(drafts_url(account_id)).json()["items"] == []
    again = client.post(f"{drafts_url(account_id, draft['id'])}/send")
    assert again.status_code == 404


def test_a_sent_reply_draft_marks_the_original(
    client: TestClient, account_id: str
) -> None:
    draft = client.post(
        drafts_url(account_id),
        json={"reference": {"message_id": "m1", "action": "reply"}, "text": "Gern."},
    ).json()
    assert client.post(f"{drafts_url(account_id, draft['id'])}/send").is_success
    original = client.get(f"/v1/accounts/{account_id}/messages/m1").json()
    assert "$answered" in original["keywords"]


def test_a_draft_without_recipients_is_not_sent(
    client: TestClient, services: Services, account_id: str
) -> None:
    draft = client.post(drafts_url(account_id), json={"text": "x"}).json()
    answer = client.post(f"{drafts_url(account_id, draft['id'])}/send")
    assert answer.status_code == 400
    assert not memory_of(services, account_id).outbox


def test_sending_a_draft_is_the_right_to_send(
    app_client: TestClient, services: Services, account_id: str
) -> None:
    drafter = bearer_for(services, Grant(accounts=[account_id], allow=["drafts"]))
    draft = app_client.post(
        drafts_url(account_id),
        json={"to": [{"email": "bob@example.com"}], "text": "x"},
        headers=drafter,
    ).json()
    url = f"{drafts_url(account_id, draft['id'])}/send"
    refused = app_client.post(url, headers=drafter)
    assert refused.status_code == 403
    assert "send_draft" in refused.json()["error"]["message"]

    sender = bearer_for(services, Grant(accounts=[account_id], allow=["send"]))
    assert app_client.post(url, headers=sender).status_code == 200


def test_a_retried_draft_send_goes_out_once(
    client: TestClient, services: Services, account_id: str
) -> None:
    draft = client.post(
        drafts_url(account_id), json={"to": [{"email": "bob@example.com"}]}
    ).json()
    url = f"{drafts_url(account_id, draft['id'])}/send"
    key = {"Idempotency-Key": "draft-once"}
    first = client.post(url, headers=key)
    second = client.post(url, headers=key)
    assert first.status_code == second.status_code == 200
    assert first.json() == second.json()
    assert len(memory_of(services, account_id).outbox) == 1
