"""Messages read: a message, a page of summaries, the changes since a
state, the outcome of a batch, an attachment's bytes. A draft is a
message."""

from __future__ import annotations

from dataclasses import dataclass, field
from datetime import datetime


@dataclass(frozen=True, slots=True)
class Address:
    """A sender or a recipient, with the name the mail gives."""

    email: str
    name: str | None = None


@dataclass(frozen=True, slots=True)
class AttachedFile:
    """An attachment as a message lists it. ``get_attachment`` reads its
    bytes by ``id``."""

    id: str
    filename: str | None
    content_type: str
    size: int
    inline: bool = False


@dataclass(frozen=True, slots=True)
class Reference:
    """The message a draft answers or forwards."""

    message_id: str
    action: str  # "reply", "reply_all" or "forward"
    forward_as: str = "inline"  # or "attachment"
    quote: bool = True


@dataclass(frozen=True, slots=True)
class MessageSummary:
    """A message in a list, and what a change of it or a draft answers."""

    id: str
    account_id: str | None
    thread_id: str | None
    folder_ids: list[str]
    subject: str | None
    sender: Address | None  # "from" in the API
    to: list[Address]
    date: datetime | None
    snippet: str | None
    unread: bool
    starred: bool
    keywords: list[str]
    has_attachments: bool


@dataclass(frozen=True, slots=True)
class Message(MessageSummary):
    """A whole message: its summary, the further headers, the bodies and
    the attachments. A draft names the message it answers."""

    cc: list[Address]
    bcc: list[Address]
    reply_to: list[Address]
    message_id_header: str | None
    in_reply_to: str | None
    text_body: str | None
    html_body: str | None
    attachments: list[AttachedFile]
    reference: Reference | None


@dataclass(frozen=True)
class Attachment:
    """An attachment's bytes, as far as the caller's limit allowed: with
    ``complete`` False, ``data`` stops at that limit."""

    data: bytes
    content_type: str
    charset: str | None  # one Python knows, else None
    filename: str | None
    complete: bool = True


@dataclass(frozen=True)
class Page:
    """A page of message summaries, of messages or of drafts."""

    items: list[MessageSummary]
    next_cursor: str | None
    # Accounts that did not answer, as "account: why".
    not_answering: list[str] = field(default_factory=list)


@dataclass(frozen=True)
class Change:
    """One change of the change feed: ids only."""

    type: str  # e.g. "message.created"
    id: str
    account_id: str
    at: datetime


@dataclass(frozen=True)
class Changes:
    """Changes after a point in the change feed, oldest first."""

    changes: list[Change]
    state: str
    more: bool


@dataclass(frozen=True)
class Failed:
    """An id a batch did not do, and why."""

    id: str
    error: str


@dataclass(frozen=True)
class Outcome:
    """A batch: the ids done, and per failed id why not."""

    done: list[str]
    failed: list[Failed]
