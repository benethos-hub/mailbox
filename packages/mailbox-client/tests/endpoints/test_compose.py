"""The body of a message as the API takes it."""

from __future__ import annotations

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
