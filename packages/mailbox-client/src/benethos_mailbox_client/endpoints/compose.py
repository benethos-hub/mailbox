"""What drafts and sending share: the body of a message as the API
takes it, made from recipients, a subject, a text, a reference and
attachments."""

from __future__ import annotations

import base64
from typing import Any

from ..models import AttachmentSource, OutgoingFile, Recipient, Reference


def message_body(
    *,
    to: list[Recipient],
    cc: list[Recipient],
    bcc: list[Recipient],
    subject: str,
    text: str,
    html: str | None,
    reference: tuple[str, str] | Reference | None,
    reply_to: list[Recipient] | None = None,
    attachments: list[OutgoingFile] | None = None,
    attachments_from: list[AttachmentSource] | None = None,
) -> dict[str, Any]:
    """The body of a draft or a message to send, as the API takes it.
    ``reference``: the message answered or forwarded, as a ``Reference``
    or as its id and the action (reply, reply_all, forward).
    ``attachments_from``: attachments of other messages of the account,
    attached before ``attachments``."""
    body: dict[str, Any] = {
        "to": [_recipient(r) for r in to],
        "cc": [_recipient(r) for r in cc],
        "bcc": [_recipient(r) for r in bcc],
        "subject": subject,
        "text": text,
    }
    if reply_to:
        body["reply_to"] = [_recipient(r) for r in reply_to]
    if html is not None:
        body["html"] = html
    if reference is not None:
        body["reference"] = _reference(reference)
    if attachments:
        body["attachments"] = [_file(f) for f in attachments]
    if attachments_from:
        body["attachments_from"] = [
            {"message_id": s.message_id, "attachment_id": s.attachment_id}
            for s in attachments_from
        ]
    return body


def _recipient(recipient: Recipient) -> dict[str, str]:
    email, name = recipient
    return {"email": email, "name": name} if name else {"email": email}


def _reference(reference: tuple[str, str] | Reference) -> dict[str, Any]:
    if not isinstance(reference, Reference):
        return {"message_id": reference[0], "action": reference[1]}
    found: dict[str, Any] = {
        "message_id": reference.message_id,
        "action": reference.action,
    }
    # Only what differs from the API's defaults.
    if reference.forward_as != "inline":
        found["forward_as"] = reference.forward_as
    if not reference.quote:
        found["quote"] = False
    return found


def _file(file: OutgoingFile) -> dict[str, str]:
    return {
        "filename": file.filename,
        "content_type": file.content_type,
        "data": base64.b64encode(file.data).decode("ascii"),
    }
