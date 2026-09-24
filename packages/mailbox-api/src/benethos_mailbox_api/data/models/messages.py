"""Messages as read, their attachments, and changes to them."""

from __future__ import annotations

from datetime import datetime
from typing import Annotated

from pydantic import BaseModel, Field


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
