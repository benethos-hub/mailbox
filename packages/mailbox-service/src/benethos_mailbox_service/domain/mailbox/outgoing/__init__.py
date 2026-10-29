"""Sending and drafts: a message composed, checked and delivered under the
grant limits on sending, the audit of sends, and a send that is not done
twice. ``Outgoing`` is the facade, ``MailboxService.outgoing``.

It reads the provider through ``..calls`` and the grants through
``..reach``. Nothing of ``mailbox`` imports it but ``service``.
"""

from __future__ import annotations

from .idempotency import Idempotency
from .sending import SendControl
from .service import Outgoing

__all__ = ["Idempotency", "Outgoing", "SendControl"]
