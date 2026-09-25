"""Messages as read, their attachments, and changes to them."""

from __future__ import annotations

from datetime import date, datetime
from typing import Annotated, Literal

from pydantic import BaseModel, Field


class MessageReference(BaseModel):
    """Reply to or forward a message of the same account. The service sets
    the recipients of a reply where none are given, the subject prefix,
    In-Reply-To, References and the quote."""

    message_id: str
    action: Literal["reply", "reply_all", "forward"]
    forward_as: Literal["inline", "attachment"] = Field(
        default="inline",
        description=(
            "`inline`: quoted with its headers, its attachments attached. "
            "`attachment`: the unchanged original as `message/rfc822`. "
            "Ignored for replies."
        ),
    )
    quote: bool = Field(
        default=True,
        description=(
            "`false`: the text holds the quote already, e.g. a stored draft "
            "edited as a whole. The link to the original stays (In-Reply-To, "
            "References, the mark on the original after sending), but nothing "
            "of the original is added: no quote, no forwarded original, none "
            "of its attachments."
        ),
    )


class Address(BaseModel):
    email: str
    name: str | None = None


class MessageSummary(BaseModel):
    id: str
    account_id: str | None = None
    thread_id: str | None = None
    folder_ids: list[str] = Field(default_factory=list)
    subject: str | None = None
    sender: Address | None = Field(default=None, alias="from")
    to: list[Address] = Field(default_factory=list)
    date: datetime | None = None
    snippet: str | None = None
    unread: bool = False
    starred: bool = False
    keywords: list[str] = Field(
        default_factory=list,
        description=(
            "Further flags, named as in JMAP: `$answered`, `$forwarded`, "
            "`$draft`, and the provider's own keywords."
        ),
    )
    has_attachments: bool = False

    model_config = {"populate_by_name": True, "serialize_by_alias": True}


class Attachment(BaseModel):
    id: str
    filename: str | None = None
    content_type: str
    size: int
    inline: bool = False


class AttachmentContent(BaseModel):
    """An attachment with its bytes, for download."""

    filename: str | None = None
    content_type: str
    data: bytes


class Message(MessageSummary):
    cc: list[Address] = Field(default_factory=list)
    bcc: list[Address] = Field(default_factory=list)
    reply_to: list[Address] = Field(default_factory=list)
    message_id_header: str | None = None
    in_reply_to: str | None = None
    text_body: str | None = None
    html_body: str | None = None
    attachments: list[Attachment] = Field(default_factory=list)
    reference: MessageReference | None = Field(
        default=None,
        description=(
            "Of a draft: the message it answers or forwards, used when it is "
            "sent. To change the draft as a whole and keep this link, pass it "
            "back to `update_draft` with `quote: false`."
        ),
    )


# Search text on one line: a line break would end the IMAP command and start
# another one of the caller's choosing.
SEARCH_TEXT_PATTERN = r"^[^\x00-\x1f\x7f]{1,200}$"


class MessageFilter(BaseModel):
    """What a list keeps. Fields left out do not filter; several narrow it
    down together."""

    text: str | None = Field(default=None, pattern=SEARCH_TEXT_PATTERN)
    sender: str | None = Field(default=None, pattern=SEARCH_TEXT_PATTERN)
    to: str | None = Field(default=None, pattern=SEARCH_TEXT_PATTERN)
    subject: str | None = Field(default=None, pattern=SEARCH_TEXT_PATTERN)
    after: date | None = None  # on or after this day
    before: date | None = None  # before this day
    unread: bool | None = None
    starred: bool | None = None
    has_attachments: bool | None = None


# A keyword as IMAP allows it: an atom, no spaces, brackets, quotes or
# wildcards, and no system flag (those start with a backslash).
KEYWORD_PATTERN = r"^[!#$&'+\-.0-9A-Z^_a-z|~]{1,100}$"


class MessageUpdate(BaseModel):
    """What ``PATCH`` changes on a message. Fields left out stay as they are."""

    unread: bool | None = None
    starred: bool | None = None
    keywords: list[Annotated[str, Field(pattern=KEYWORD_PATTERN)]] | None = Field(
        default=None,
        max_length=50,
        description="Replaces the list of keywords.",
    )
    folder_ids: list[str] | None = Field(
        default=None,
        min_length=1,
        max_length=20,
        description=(
            "The folders the message is to be in. A change moves it; the id "
            "stays. An IMAP message is in exactly one folder."
        ),
    )
