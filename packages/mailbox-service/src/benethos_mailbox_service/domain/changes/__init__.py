"""Changes: what changed in a mailbox, for clients (CONCEPT 6.5).

A change is not an activity. An activity says what was done in the
service and goes to the log (``domain/activity/``). A change goes to
clients through the change feed and the webhooks.
"""

from __future__ import annotations

from .catalogue import (
    AccountNeedsSignIn,
    MailboxChange,
    MessagesChanged,
    MessagesCreated,
    MessagesDeleted,
    MessageSent,
    MessagesUpdated,
)
from .feed import ChangeFeed

__all__ = [
    "AccountNeedsSignIn",
    "ChangeFeed",
    "MailboxChange",
    "MessageSent",
    "MessagesChanged",
    "MessagesCreated",
    "MessagesDeleted",
    "MessagesUpdated",
]
