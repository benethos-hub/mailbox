"""Sending tools: a new mail, a draft. A send cannot be taken back."""

from __future__ import annotations

import hashlib
from typing import Any

from benethos_mailbox_common.values import canonical

from .. import render
from .base import changes, client
from .compose import Action, Addresses, Html, OriginalId, Text, composed


def _idempotency_key(tool: str, account_id: str, arguments: Any) -> str:
    """The same call gives the same key: the service answers a repeat within
    24 hours with the first result instead of sending twice. Written as the
    service writes the fingerprint of a request (``canonical``): keys
    sorted, no spaces, ASCII."""
    call = canonical.canonical([tool, account_id, arguments])
    return "mcp-" + hashlib.sha256(call.encode("utf-8")).hexdigest()


async def send_message(
    account_id: str,
    to: Addresses = None,
    cc: Addresses = None,
    bcc: Addresses = None,
    subject: str = "",
    text: Text = "",
    html: Html = None,
    original_id: OriginalId = None,
    action: Action = "reply",
) -> dict[str, Any]:
    """Send a mail at once. It cannot be taken back. With original_id it
    answers or forwards that message, and a reply without recipients goes
    to its sender. The same call repeated within 24 hours sends nothing and
    answers the first result. refused lists recipients the server did not
    take."""
    body = composed(to, cc, bcc, subject, text, html, original_id, action)
    key = _idempotency_key("send_message", account_id, body)
    return render.sent(await client().send_message(account_id, body, key))


async def send_draft(account_id: str, draft_id: str) -> dict[str, Any]:
    """Send a draft as it is stored. It cannot be taken back. Afterwards the
    draft is gone and a copy is in the sent folder."""
    key = _idempotency_key("send_draft", account_id, draft_id)
    return render.sent(await client().send_draft(account_id, draft_id, key))


TOOLS = (
    # A repeated send within 24 hours sends nothing (Idempotency-Key). It is
    # still marked as not idempotent: after that time it sends again.
    changes(
        send_message,
        "Send a mail",
        "send",
        "send_message",
        destructive=True,
        idempotent=False,
    ),
    changes(
        send_draft,
        "Send a draft",
        "send",
        "send_draft",
        destructive=True,
        idempotent=False,
    ),
)
