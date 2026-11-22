"""The error ``MessageGoneError``."""

from __future__ import annotations

from .mailbox_refused import MailboxRefusedError

__all__ = ["MessageGoneError"]


class MessageGoneError(MailboxRefusedError):
    """The message is not there any more: deleted, or moved out of reach.
    The same ``code`` as its base, so logs and metrics count it alike."""
