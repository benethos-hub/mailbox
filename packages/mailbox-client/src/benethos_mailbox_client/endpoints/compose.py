"""What drafts and sending share: the body of a message as the API
takes it, made from recipients, a subject, a text and a reference."""

from __future__ import annotations

from typing import Any

from ..models import Recipient


def message_body(
    *,
    to: list[Recipient],
    cc: list[Recipient],
    bcc: list[Recipient],
    subject: str,
    text: str,
    html: str | None,
    reference: tuple[str, str] | None,
) -> dict[str, Any]:
    """The body of a draft or a message to send, as the API takes it.
    ``reference``: the id of the message answered or forwarded, and the
    action (reply, reply_all, forward)."""
    body: dict[str, Any] = {
        "to": [_recipient(r) for r in to],
        "cc": [_recipient(r) for r in cc],
        "bcc": [_recipient(r) for r in bcc],
        "subject": subject,
        "text": text,
    }
    if html is not None:
        body["html"] = html
    if reference is not None:
        body["reference"] = {"message_id": reference[0], "action": reference[1]}
    return body


def _recipient(recipient: Recipient) -> dict[str, str]:
    email, name = recipient
    return {"email": email, "name": name} if name else {"email": email}
