"""The IMAP provider, registry key ``imap``."""

from __future__ import annotations

from .provider import ImapProvider, probe

__all__ = ["ImapProvider", "probe"]
