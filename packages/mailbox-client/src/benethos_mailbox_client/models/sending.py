"""Mail going out: who it goes to, and what a send answered."""

from __future__ import annotations

from dataclasses import dataclass

# An address with an optional display name.
Recipient = tuple[str, str | None]


@dataclass(frozen=True, slots=True)
class Sent:
    message_id_header: str | None
    refused: list[str]
    # Of a reply or a forward: whether the original carries the mark now.
    original_marked: bool | None = None


@dataclass(frozen=True, slots=True)
class OutgoingFile:
    """A file to attach to a draft or a message to send."""

    filename: str
    data: bytes
    content_type: str = "application/octet-stream"


@dataclass(frozen=True, slots=True)
class AttachmentSource:
    """An attachment of another message of the same account, to attach as
    it is."""

    message_id: str
    attachment_id: str
