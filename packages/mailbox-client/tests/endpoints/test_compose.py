"""The body of a message as the API takes it."""

from __future__ import annotations

from benethos_mailbox_client import (
    AttachmentSource,
    OutgoingFile,
    Reference,
    message_body,
)

from ..fake_api import BODY


def test_message_body() -> None:
    assert BODY == {
        "to": [{"email": "a@x.org", "name": "A"}],
        "cc": [{"email": "c@x.org"}],
        "bcc": [],
        "subject": "Hi",
        "text": "Hello",
        "html": "<p>Hello</p>",
        "reference": {"message_id": "msg_1", "action": "reply"},
    }


def test_a_body_with_attachments_and_a_full_reference() -> None:
    body = message_body(
        to=[],
        cc=[],
        bcc=[],
        subject="Fwd: Offer",
        text="Here.",
        html=None,
        reference=Reference("msg_1", "forward", forward_as="attachment", quote=False),
        reply_to=[("office@x.org", "Office")],
        attachments=[OutgoingFile("a.ics", b"BEGIN", "text/calendar")],
        attachments_from=[AttachmentSource("msg_2", "att_0")],
    )
    assert body["reference"] == {
        "message_id": "msg_1",
        "action": "forward",
        "forward_as": "attachment",
        "quote": False,
    }
    assert body["reply_to"] == [{"email": "office@x.org", "name": "Office"}]
    assert body["attachments"] == [
        {"filename": "a.ics", "content_type": "text/calendar", "data": "QkVHSU4="}
    ]
    assert body["attachments_from"] == [
        {"message_id": "msg_2", "attachment_id": "att_0"}
    ]
