"""Mail: folders and messages of one account and across accounts,
sending and drafts, the grant limits on sending and its audit, links to
attachments.

``MailboxService`` is the facade. Sending is ``MailboxService.outgoing``,
links to attachments ``AttachmentLinks``.
"""

from __future__ import annotations

from .folders import find_folder
from .idempotency import Idempotency
from .links import (
    LINK_GONE,
    LINK_SECONDS,
    SECRET_LENGTH,
    AttachmentLinks,
    SharedLink,
)
from .sending import SendControl
from .service import MailboxService

__all__ = [
    "LINK_GONE",
    "LINK_SECONDS",
    "SECRET_LENGTH",
    "AttachmentLinks",
    "Idempotency",
    "MailboxService",
    "SendControl",
    "SharedLink",
    "find_folder",
]
