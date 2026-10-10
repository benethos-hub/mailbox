"""Mail itself, nothing of Mailbox. Callers import the modules from here,
``from benethos_mailbox_common.mail import plaintext``."""

from __future__ import annotations

from . import addresses, plaintext

__all__ = ["addresses", "plaintext"]
