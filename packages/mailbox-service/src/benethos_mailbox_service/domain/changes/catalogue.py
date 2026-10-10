"""The kinds of change, one class each (docs/REFACTORING.md section 3).

A change says what changed in a mailbox and goes to clients: through the
change feed and the posts to webhooks. ``kind`` is its name there, and so
part of the API. A change is recorded as a class, never by its name:
``feed.record(MessagesUpdated(account_id, ids))``.
"""

from __future__ import annotations

from collections.abc import Mapping, Sequence
from dataclasses import dataclass, field
from typing import ClassVar

from ...data.models import ChangeKind


@dataclass(frozen=True, slots=True)
class MailboxChange:
    """What changed in one account's mailbox."""

    kind: ClassVar[ChangeKind]
    account_id: str

    def ids(self) -> Sequence[str]:
        """What the change names, one record each: here the account."""
        return [self.account_id]

    def folder_of(self, record_id: str) -> str | None:
        """The folder of what a record names, None where unknown."""
        return None


@dataclass(frozen=True, slots=True)
class MessagesChanged(MailboxChange):
    """A change of messages: the three kinds the change feed answers.
    Webhooks hear of all five."""

    message_ids: Sequence[str]
    # Each message's folder where it is known: where it is now, or for a
    # deletion where it was.
    folders: Mapping[str, str] = field(default_factory=dict, compare=False, hash=False)

    def ids(self) -> Sequence[str]:
        return self.message_ids

    def folder_of(self, record_id: str) -> str | None:
        return self.folders.get(record_id) or None


@dataclass(frozen=True, slots=True)
class MessagesCreated(MessagesChanged):
    """Messages arrived."""

    kind: ClassVar[ChangeKind] = "message.created"


@dataclass(frozen=True, slots=True)
class MessagesUpdated(MessagesChanged):
    """Messages moved, or their flags changed."""

    kind: ClassVar[ChangeKind] = "message.updated"


@dataclass(frozen=True, slots=True)
class MessagesDeleted(MessagesChanged):
    """Messages are gone."""

    kind: ClassVar[ChangeKind] = "message.deleted"


@dataclass(frozen=True, slots=True)
class MessageSent(MailboxChange):
    """A mail went out. ``message_id``: its copy in the sent folder, or
    else its Message-ID header."""

    kind: ClassVar[ChangeKind] = "message.sent"
    message_id: str

    def ids(self) -> Sequence[str]:
        return [self.message_id]


@dataclass(frozen=True, slots=True)
class AccountNeedsSignIn(MailboxChange):
    """The provider refused the account's sign-in: a person signs in again."""

    kind: ClassVar[ChangeKind] = "account.needs_reauth"
