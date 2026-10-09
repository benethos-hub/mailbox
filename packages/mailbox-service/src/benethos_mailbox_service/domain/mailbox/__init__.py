"""Mail: folders and messages of one account and across accounts,
sending and drafts, the grant limits on sending and its audit.

``MailboxService`` is the facade. Sending is ``MailboxService.outgoing``.
"""

from __future__ import annotations

from .folders import find_folder
from .idempotency import Idempotency
from .sending import SendControl
from .service import MailboxService

__all__ = [
    "Idempotency",
    "MailboxService",
    "SendControl",
    "find_folder",
]
