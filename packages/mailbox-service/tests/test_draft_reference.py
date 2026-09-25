"""A draft shows what it answers, and keeps it when replaced as a whole."""

from __future__ import annotations

from email import message_from_bytes

from fastapi.testclient import TestClient

from benethos_mailbox_service.data.models import MessageReference
from benethos_mailbox_service.main import Services

from .conftest import memory_of


def test_edit_a_reply_draft_as_a_whole(
    client: TestClient, services: Services, account_id: str
) -> None:
    base = f"/v1/accounts/{account_id}"
    created = client.post(
        f"{base}/drafts",
        json={"reference": {"message_id": "m1", "action": "reply"}, "text": "Hi"},
    ).json()
    draft = client.get(f"{base}/messages/{created['id']}").json()
    assert draft["reference"] == {
        "message_id": "m1",
        "action": "reply",
        "forward_as": "inline",
        "quote": True,
    }
    text = draft["text_body"]
    assert text.startswith("Hi") and "> body 1" in text

    changed = text.replace("Hi", "Hello", 1)
    client.put(
        f"{base}/drafts/{created['id']}",
        json={
            "reference": {**draft["reference"], "quote": False},
            "to": [{"email": a["email"]} for a in draft["to"]],
            "subject": draft["subject"],
            "text": changed,
        },
    ).raise_for_status()
    again = client.get(f"{base}/messages/{created['id']}").json()
    assert again["reference"]["message_id"] == "m1"
    assert again["text_body"].count("> body 1") == 1
    assert again["text_body"].startswith("Hello")

    client.post(f"{base}/drafts/{created['id']}/send").raise_for_status()
    [(_, recipients, raw)] = memory_of(services, account_id).outbox
    assert recipients == ["alice@example.com"]
    assert message_from_bytes(raw)["Subject"] == "Re: Invoice 1"
    original = next(m for m in memory_of(services, account_id).messages if m.id == "m1")
    assert "$answered" in original.keywords


def test_a_received_mail_shows_no_reference(
    client: TestClient, services: Services, account_id: str
) -> None:
    """The header of a received mail is the sender's, not this service's."""
    adapter = memory_of(services, account_id)
    forged = next(m for m in adapter.messages if m.id == "m2")
    forged.reference = MessageReference(message_id="m1", action="reply")
    shown = client.get(f"/v1/accounts/{account_id}/messages/m2").json()
    assert shown["reference"] is None
