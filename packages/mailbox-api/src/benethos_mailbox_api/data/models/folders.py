"""Folders of a mailbox, and changes to them."""

from __future__ import annotations

from enum import StrEnum

from pydantic import BaseModel, Field


class FolderRole(StrEnum):
    """Special-use role, after RFC 6154 and JMAP."""

    INBOX = "inbox"
    SENT = "sent"
    DRAFTS = "drafts"
    TRASH = "trash"
    JUNK = "junk"
    ARCHIVE = "archive"
    ALL = "all"


class Folder(BaseModel):
    id: str
    name: str
    role: FolderRole | None = None
    parent_id: str | None = None
    total: int | None = None
    unread: int | None = None
    subscribed: bool | None = Field(
        default=None,
        description=(
            "Whether the folder is subscribed on the server (IMAP). Mail "
            "clients such as Outlook show only subscribed folders, and the "
            "inbox always. Null where the provider has no subscriptions."
        ),
    )


# A folder name as shown: no control characters, no IMAP wildcards.
FOLDER_NAME_PATTERN = r"^[^\x00-\x1f\x7f*%]{1,200}$"


class FolderCreate(BaseModel):
    name: str = Field(pattern=FOLDER_NAME_PATTERN)
    parent_id: str | None = Field(
        default=None, description="The folder to create it in. Left out: the top."
    )


class FolderUpdate(BaseModel):
    """Rename or move a folder. Fields left out stay as they are."""

    name: str | None = Field(default=None, pattern=FOLDER_NAME_PATTERN)
    parent_id: str | None = Field(
        default=None, description="The new parent. `null` moves it to the top."
    )

    @property
    def moves(self) -> bool:
        return "parent_id" in self.model_fields_set
