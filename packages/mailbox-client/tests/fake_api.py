"""A REST API that answers every request alike and records each, and
the answers the endpoint tests share."""

from __future__ import annotations

import json
from typing import Any

import httpx

from benethos_mailbox_client import message_body


class FakeApi:
    """Answers every request with ``answer`` and ``status``, ``None`` as
    204, and records each."""

    def __init__(self, answer: Any = None, status: int = 200) -> None:
        self.answer, self.status = answer, status
        self.seen: list[httpx.Request] = []

    def __call__(self, request: httpx.Request) -> httpx.Response:
        self.seen.append(request)
        if self.answer is None:
            return httpx.Response(204)
        return httpx.Response(self.status, json=self.answer)

    def call(self) -> tuple[str, str, dict[str, str], Any]:
        """The one request: method, path, query and body."""
        [request] = self.seen
        body = json.loads(request.content) if request.content else None
        return request.method, request.url.path, dict(request.url.params), body


ME = {
    "user_id": "usr_1",
    "name": "me",
    "accounts": [
        {
            "id": "acc_1",
            "email": "me@example.com",
            "display_name": "Me",
            "operations": ["list_messages"],
            "warnings": ["reads_and_sends"],
            "sending": [
                {"recipients": ["a@x.org"], "max_sends_per_day": 5, "sends_left": 4}
            ],
            "capabilities": ["flags"],
        },
        {"id": "acc_2", "email": "two@example.com"},
    ],
    "operations": ["list_users"],
}

FOLDER = {"id": "fld_1", "name": "Inbox", "role": "inbox", "unread": 2, "total": 9}

SUMMARY = {
    "id": "msg_1",
    "account_id": "acc_1",
    "thread_id": "thr_1",
    "folder_ids": ["fld_1"],
    "subject": "Hi",
    "from": {"email": "a@example.com", "name": "Ann"},
    "to": [{"email": "me@example.com", "name": None}],
    "date": "2026-10-01T08:00:00Z",
    "snippet": "Hello",
    "unread": True,
    "starred": False,
    "keywords": ["work"],
    "has_attachments": True,
}

MESSAGE = {
    **SUMMARY,
    "cc": [{"email": "c@example.com"}],
    "bcc": [],
    "reply_to": [],
    "message_id_header": "<m1@example.com>",
    "in_reply_to": None,
    "text_body": "Hello",
    "html_body": "<p>Hello</p>",
    "attachments": [
        {
            "id": "att_0",
            "filename": "a.pdf",
            "content_type": "application/pdf",
            "size": 12,
            "inline": False,
        }
    ],
    "reference": None,
}

PAGE = {
    "items": [SUMMARY],
    "next_cursor": "c2",
    "incomplete": [{"account_id": "acc_2", "message": "timed out"}],
}

SENT = {"message_id_header": "<m@x>", "refused": ["b@x.org"]}

BODY = message_body(
    to=[("a@x.org", "A")],
    cc=[("c@x.org", None)],
    bcc=[],
    subject="Hi",
    text="Hello",
    html="<p>Hello</p>",
    reference=("msg_1", "reply"),
)

ACCOUNT = {
    "id": "acc_1",
    "provider": "imap",
    "email": "me@example.com",
    "display_name": None,
    "status": "connected",
    "credentials": [{"field": "password", "updated_at": "2026-10-01T00:00:00Z"}],
    "settings": {"host": "imap.example.com", "port": 993},
    "capabilities": ["flags", "folders"],
}

USER = {
    "id": "usr_1",
    "name": "desktop",
    "roles": ["readers"],
    "service": [],
    "grants": [
        {
            "accounts": ["acc_1"],
            "allow": ["mail.read", "send"],
            "recipients": ["*@example.org"],
            "max_sends_per_day": 20,
            "expires_at": "2026-12-31T23:00:00Z",
        }
    ],
    "disabled": False,
    "ui_sign_in": False,
    "has_password": False,
    "must_change": False,
    "last_sign_in_at": None,
    "second_factor": False,
}
