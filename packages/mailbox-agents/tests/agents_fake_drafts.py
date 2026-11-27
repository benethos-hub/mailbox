"""The drafts of the fake mailbox service: a draft is made from the body
of create_draft, kept as a message in the drafts folder with its
reference, and listed as the service lists drafts."""

from __future__ import annotations

import json
from typing import Any

import httpx


def draft_of(account: str, number: int, body: dict[str, Any]) -> dict[str, Any]:
    """The draft a body of create_draft makes, as get_message answers it."""
    return {
        "id": f"draft{number}",
        "account_id": account,
        "thread_id": None,
        "folder_ids": ["drafts"],
        "subject": body.get("subject") or None,
        "from": None,
        "to": body.get("to", []),
        "cc": body.get("cc", []),
        "bcc": body.get("bcc", []),
        "reply_to": [],
        "date": "2026-11-17T08:00:00+00:00",
        "received": "2026-11-17T08:00:00+00:00",
        "snippet": None,
        "unread": False,
        "starred": False,
        "keywords": [],
        "has_attachments": False,
        "message_id_header": None,
        "in_reply_to": None,
        "text_body": body.get("text"),
        "html_body": None,
        "attachments": [],
        "reference": body.get("reference"),
    }


def made(
    messages: dict[tuple[str, str], dict[str, Any]],
    account: str,
    request: httpx.Request,
) -> httpx.Response:
    """Keep the draft of the body of ``request``, answer its summary."""
    number = sum(1 for m in messages.values() if m["folder_ids"] == ["drafts"]) + 1
    draft = draft_of(account, number, json.loads(request.content))
    messages[(account, draft["id"])] = draft
    return httpx.Response(201, json=draft)


def listed(
    messages: dict[tuple[str, str], dict[str, Any]],
    account: str,
    request: httpx.Request,
) -> httpx.Response:
    """The drafts of ``account``, the newest first, in pages of ``limit``,
    50 by default, as the service lists them."""
    items = [
        m
        for (a, _), m in messages.items()
        if a == account and m["folder_ids"] == ["drafts"]
    ][::-1]
    cursor = int(request.url.params.get("cursor", "0"))
    limit = int(request.url.params.get("limit", "50"))
    more = cursor + limit < len(items)
    return httpx.Response(
        200,
        json={
            "items": items[cursor : cursor + limit],
            "next_cursor": str(cursor + limit) if more else None,
        },
    )
