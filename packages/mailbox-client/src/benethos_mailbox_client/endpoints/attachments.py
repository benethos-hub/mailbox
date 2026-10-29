"""The attachments of a message: their bytes, and a link to one for
another service."""

from __future__ import annotations

from typing import Any

from ..attachments import media_type
from ..calls import ATTACHMENT_TIMEOUT, Call, as_is, given, path
from ..models import AttachmentLink, Secret
from .readings import time


def get_attachment(account_id: str, message_id: str, attachment_id: str) -> Call[Any]:
    """The attachment's bytes. Read as a stream, not as JSON."""
    return Call(
        "GET",
        path(
            "accounts", account_id, "messages", message_id, "attachments", attachment_id
        ),
        as_is,
        timeout=ATTACHMENT_TIMEOUT,
    )


def share_attachment(
    account_id: str,
    message_id: str,
    attachment_id: str,
    *,
    expires_in: int | None = None,
) -> Call[AttachmentLink]:
    """A link to the attachment for another service, which fetches the
    file itself: once, with GET and no token, until ``expires_at``.
    ``expires_in`` asks for fewer seconds than the service gives. Whoever
    holds the URL fetches the file. No method of this package uses it."""
    return Call(
        "POST",
        path(
            "accounts",
            account_id,
            "messages",
            message_id,
            "attachments",
            attachment_id,
            "links",
        ),
        _link,
        json=given({"expires_in": expires_in}),
    )


def _link(found: dict[str, Any]) -> AttachmentLink:
    return AttachmentLink(
        url=Secret(str(found["url"])),
        expires_at=time(found["expires_at"]),
        content_type=media_type(str(found["content_type"])),
        size=int(found["size"]),
        filename=found.get("filename"),
    )
