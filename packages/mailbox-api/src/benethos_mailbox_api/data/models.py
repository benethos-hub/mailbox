"""Provider-neutral data model.

Every provider adapter maps into these types, the domain works with them, and
the web layer serves them. They know nothing of HTTP, SQL or any mail protocol.
"""

from __future__ import annotations

from datetime import datetime
from enum import StrEnum
from typing import Generic, TypeVar

from pydantic import BaseModel, Field


class ProviderType(StrEnum):
    IMAP = "imap"
    GMAIL = "gmail"
    MICROSOFT = "microsoft"
    MEMORY = "memory"


class AccountStatus(StrEnum):
    CONNECTED = "connected"
    NEEDS_REAUTH = "needs_reauth"
    DISABLED = "disabled"


class FolderRole(StrEnum):
    """Special-use role, after RFC 6154 and JMAP."""

    INBOX = "inbox"
    SENT = "sent"
    DRAFTS = "drafts"
    TRASH = "trash"
    JUNK = "junk"
    ARCHIVE = "archive"
    ALL = "all"


class Address(BaseModel):
    email: str
    name: str | None = None


class Account(BaseModel):
    id: str
    provider: ProviderType
    email: str
    display_name: str | None = None
    status: AccountStatus = AccountStatus.CONNECTED


class Grant(BaseModel):
    """Rights on accounts: operation or group names, account ids or ``*``."""

    accounts: list[str]
    allow: list[str]


class User(BaseModel):
    """Someone or something that calls the API."""

    id: str
    name: str
    roles: list[str] = Field(default_factory=list)
    grants: list[Grant] = Field(default_factory=list)
    disabled: bool = False


class Role(BaseModel):
    """A named, reusable set of grants."""

    id: str
    grants: list[Grant] = Field(default_factory=list)


class Folder(BaseModel):
    id: str
    name: str
    role: FolderRole | None = None
    parent_id: str | None = None
    total: int | None = None
    unread: int | None = None


class MessageSummary(BaseModel):
    id: str
    thread_id: str | None = None
    folder_ids: list[str] = Field(default_factory=list)
    subject: str | None = None
    sender: Address | None = Field(default=None, alias="from")
    to: list[Address] = Field(default_factory=list)
    date: datetime | None = None
    snippet: str | None = None
    unread: bool = False
    starred: bool = False
    has_attachments: bool = False

    model_config = {"populate_by_name": True, "serialize_by_alias": True}


class Attachment(BaseModel):
    id: str
    filename: str | None = None
    content_type: str
    size: int
    inline: bool = False


class Message(MessageSummary):
    cc: list[Address] = Field(default_factory=list)
    bcc: list[Address] = Field(default_factory=list)
    reply_to: list[Address] = Field(default_factory=list)
    message_id_header: str | None = None
    in_reply_to: str | None = None
    text_body: str | None = None
    html_body: str | None = None
    attachments: list[Attachment] = Field(default_factory=list)


T = TypeVar("T")


class Page(BaseModel, Generic[T]):
    """One page of a list. ``next_cursor`` is opaque, absent on the last page."""

    items: list[T]
    next_cursor: str | None = None
