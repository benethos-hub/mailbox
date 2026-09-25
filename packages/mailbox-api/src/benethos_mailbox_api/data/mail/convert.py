"""A parsed message to the neutral model: what the message itself says.

Headers, addresses, date, bodies and attachments, whatever protocol brought
the bytes. What only a protocol knows (ids, folders, flags) the adapter adds.
"""

from __future__ import annotations

from typing import Any

from ...errors import NotFoundError
from ..models import Attachment, AttachmentContent
from .compose import REFERENCE_HEADER, read_reference
from .parse import ParsedMessage


def summary_fields(msg: ParsedMessage) -> dict[str, Any]:
    """Subject, sender, recipients and date, from the headers alone."""
    return {
        "subject": msg.subject,
        "from": msg.sender,
        "to": msg.to,
        "date": msg.date,
        "has_attachments": msg.content_type.startswith("multipart/mixed"),
    }


def thread_fields(msg: ParsedMessage) -> dict[str, Any]:
    """The headers that tie a message to others: its own id, what it
    answers, and the reference a draft of this service keeps."""
    return {
        "message_id_header": msg.message_id,
        "in_reply_to": msg.header("in-reply-to"),
        "reference": read_reference(msg.header(REFERENCE_HEADER)),
    }


def message_fields(msg: ParsedMessage) -> dict[str, Any]:
    """What a whole message adds to its summary: further addresses, the
    thread headers, the bodies and the attachments."""
    attachments = [
        Attachment(
            id=attachment_id(index),
            filename=part.filename,
            content_type=part.content_type,
            size=part.size,
            inline=part.inline,
        )
        for index, part in enumerate(msg.attachments)
    ]
    return {
        "cc": msg.cc,
        "bcc": msg.bcc,
        "reply_to": msg.reply_to,
        **thread_fields(msg),
        "text_body": msg.text,
        "html_body": msg.html,
        "attachments": attachments,
        "has_attachments": bool(attachments),
    }


def attachment_id(index: int) -> str:
    """The id of an attachment: its place in the message."""
    return f"att_{index}"


def attachment(msg: ParsedMessage, attachment_id: str) -> AttachmentContent:
    """One attachment with its bytes, by the id ``message_fields`` gave it."""
    if not attachment_id.startswith("att_") or not attachment_id[4:].isdigit():
        raise NotFoundError(f"attachment {attachment_id} not found")
    index = int(attachment_id[4:])
    if index >= len(msg.attachments):
        raise NotFoundError(f"attachment {attachment_id} not found")
    part = msg.attachments[index]
    return AttachmentContent(
        filename=part.filename, content_type=part.content_type, data=part.payload
    )
