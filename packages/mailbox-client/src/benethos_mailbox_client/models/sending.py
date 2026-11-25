"""Mail going out: who it goes to, and what a send answered."""

from __future__ import annotations

from dataclasses import dataclass
from datetime import datetime

from .messages import Address

# An address with an optional display name: an Address, or its email and
# name as a pair.
Recipient = Address | tuple[str, str | None]


@dataclass(frozen=True, slots=True)
class Sent:
    message_id_header: str
    refused: list[str]
    # Of a reply or a forward: whether the original carries the mark now.
    original_marked: bool | None = None
    # The copy in the sent folder, where the service put one.
    sent_copy_id: str | None = None


@dataclass(frozen=True, slots=True)
class OutboxEntry:
    """A send in the outbox: put in with ``outbox`` or ``send_at``, sent in
    the background. ``state`` is ``queued``, ``sending``, ``copying``,
    ``sent``, ``failed``, ``unknown`` or ``cancelled``. ``last_error`` is
    the code of the last failure, or why it ended."""

    id: str
    account_id: str
    user_id: str
    operation: str
    draft_id: str
    message_id_header: str
    recipients: list[str]
    state: str
    attempts: int
    due_at: datetime
    expires_at: datetime
    send_at: datetime | None
    last_error: str | None
    created_at: datetime
    finished_at: datetime | None


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
