"""A parsed message to the neutral model: what the message itself says.

Headers, addresses, date, bodies and attachments, whatever protocol brought
the bytes. What only a protocol knows (ids, folders, flags) the adapter adds.
Works on ``parse.ParsedMessage`` by attribute, without the parser library.
"""

from __future__ import annotations

from datetime import UTC, datetime
from typing import Any

from ...errors import NotFoundError
from ..models import Address, Attachment, AttachmentContent


def summary_fields(msg: Any) -> dict[str, Any]:
    """Subject, sender, recipients and date, from the headers alone."""
    content_type = (_first(_headers(msg).get("content-type")) or "").lower()
    sender = msg.from_values
    return {
        "subject": msg.subject or None,
        "from": _address(sender) if sender and sender.email else None,
        "to": _addresses(msg.to_values),
        "date": _date(msg.date),
        "has_attachments": content_type.startswith("multipart/mixed"),
    }


def message_fields(msg: Any) -> dict[str, Any]:
    """What a whole message adds to its summary: further addresses, the
    thread headers, the bodies and the attachments."""
    attachments = [
        Attachment(
            id=f"att_{index}",
            filename=part.filename or None,
            content_type=part.content_type or "application/octet-stream",
            size=part.size,
            inline=(part.content_disposition or "").lower() == "inline",
        )
        for index, part in enumerate(msg.attachments)
    ]
    headers = _headers(msg)
    return {
        "cc": _addresses(msg.cc_values),
        "bcc": _addresses(msg.bcc_values),
        "reply_to": _addresses(msg.reply_to_values),
        "message_id_header": _first(headers.get("message-id")),
        "in_reply_to": _first(headers.get("in-reply-to")),
        "text_body": msg.text or None,
        "html_body": msg.html or None,
        "attachments": attachments,
        "has_attachments": bool(attachments),
    }


def message_id_header(msg: Any) -> str | None:
    value = _first(_headers(msg).get("message-id"))
    return "".join(value.split()) if value else None


def attachment(msg: Any, attachment_id: str) -> AttachmentContent:
    """One attachment with its bytes, by the id ``message_fields`` gave it."""
    if not attachment_id.startswith("att_") or not attachment_id[4:].isdigit():
        raise NotFoundError(f"attachment {attachment_id} not found")
    index = int(attachment_id[4:])
    if index >= len(msg.attachments):
        raise NotFoundError(f"attachment {attachment_id} not found")
    part = msg.attachments[index]
    return AttachmentContent(
        filename=part.filename or None,
        content_type=part.content_type or "application/octet-stream",
        data=part.payload,
    )


def unicode_address(email: str) -> str:
    """An address with an internationalised domain in Unicode: on the wire it
    travels as punycode (``xn--``), the API shows it as people write it."""
    local, at, domain = email.rpartition("@")
    if not at or "xn--" not in domain.lower():
        return email
    try:
        return f"{local}@{domain.encode('ascii').decode('idna')}"
    except UnicodeError:
        return email


def _headers(msg: Any) -> dict[str, Any]:
    return {k.lower(): v for k, v in msg.headers.items()}


def _address(value: Any) -> Address:
    return Address(email=unicode_address(value.email), name=value.name or None)


def _addresses(values: Any) -> list[Address]:
    return [_address(v) for v in values or () if v.email]


def _first(value: Any) -> str | None:
    if isinstance(value, tuple | list):
        return str(value[0]).strip() if value else None
    return str(value).strip() if value else None


def _date(value: datetime | None) -> datetime | None:
    # imap-tools answers an unparsable Date header with 1900-01-01.
    if value is None or value.year <= 1900:
        return None
    # A Date header without a zone is taken as UTC, so every date carries one.
    return value if value.tzinfo is not None else value.replace(tzinfo=UTC)
