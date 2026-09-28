"""Mail: folders and messages of one account and across accounts,
sending and drafts, the grant limits on sending and its audit.

``MailboxService`` is the facade. Sending is ``MailboxService.outgoing``.
"""

from __future__ import annotations

from .idempotency import Idempotency
from .sending import SendControl
from .service import MailboxService, find_folder

__all__ = [
    "Idempotency",
    "MailboxService",
    "SendControl",
    "find_folder",
]
