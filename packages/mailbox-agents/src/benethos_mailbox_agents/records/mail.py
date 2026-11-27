"""What the agents see of a mailbox.

``sources/mailbox.py`` turns the client's answers into these, so no other
module needs to know the client. None of them is ever stored: the state
file holds a :class:`MessageRef` and fetches the rest again by it.
"""

from __future__ import annotations

from datetime import datetime
from typing import Literal, get_args

from pydantic import BaseModel, ConfigDict

__all__ = [
    "DISCARD_ROLES",
    "EVENTS",
    "Address",
    "Attachment",
    "Event",
    "EventType",
    "FolderRef",
    "MailMessage",
    "OWN_ROLES",
    "MessageRef",
    "Thread",
]


class _Record(BaseModel):
    model_config = ConfigDict(frozen=True, extra="forbid")


class MessageRef(_Record):
    """A message by its ids: all the state file ever holds of one."""

    account_id: str
    message_id: str


# The events of the change feed this package knows, and an agent may ask
# for.
EventType = Literal[
    "message.created", "message.updated", "message.deleted", "message.sent"
]
EVENTS: frozenset[str] = frozenset(get_args(EventType))


class Event(_Record):
    """One entry of the change feed."""

    type: EventType
    ref: MessageRef
    at: datetime


class Address(_Record):
    email: str
    name: str | None = None

    @property
    def domain(self) -> str:
        """The part after the last ``@``, in lower case."""
        return self.email.rpartition("@")[2].lower()


class Attachment(_Record):
    filename: str | None
    content_type: str
    size: int
    inline: bool = False


# The roles of the folders no agent moves a message into, makes a folder
# below or looks in: a move there is a deletion, and a message there is not
# the owner's to file.
DISCARD_ROLES = frozenset({"trash", "junk", "spam"})

# The roles of the folders of the owner's own mail, being written or sent:
# no actor takes a message there, and no forward is drafted of one.
OWN_ROLES = frozenset({"drafts", "sent"})


class FolderRef(_Record):
    """A folder a message is in, with its path from the top, ``/`` between
    the names."""

    id: str
    name: str
    role: str | None = None
    path: str


class MailMessage(_Record):
    """A message as an agent reads it. ``text`` is its text part, else
    the visible text of its HTML part, hidden HTML content already
    dropped."""

    ref: MessageRef
    thread_id: str | None = None
    folders: tuple[FolderRef, ...] = ()
    subject: str | None = None
    sender: Address | None = None
    to: tuple[Address, ...] = ()
    cc: tuple[Address, ...] = ()
    date: datetime | None = None
    received: datetime | None = None
    keywords: tuple[str, ...] = ()
    text: str = ""
    attachments: tuple[Attachment, ...] = ()
    message_id_header: str | None = None
    in_reply_to: str | None = None
    # What the account's receiving server stated about the domain of the
    # sender, as the service answers it. unknown when it cannot tell.
    sender_check: Literal["pass", "fail", "unknown"] = "unknown"

    def in_role(self, role: str) -> bool:
        """Whether the message is in a folder of ``role``, such as ``inbox``."""
        return any(folder.role == role for folder in self.folders)

    def has_keyword(self, keyword: str) -> bool:
        """Whether the message carries ``keyword``, in any case. IMAP
        keywords ignore case, and a service may answer them in lower case
        (measured 2026-11-18 at Stalwart through service 0.7.5)."""
        wanted = keyword.casefold()
        return any(k.casefold() == wanted for k in self.keywords)


class Thread(_Record):
    """A conversation, its messages oldest first."""

    id: str
    messages: tuple[MailMessage, ...] = ()
