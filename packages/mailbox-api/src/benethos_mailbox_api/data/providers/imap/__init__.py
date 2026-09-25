"""The IMAP provider, registry key ``imap``."""

from __future__ import annotations

from .provider import ImapProvider, probe, settings_from

__all__ = ["ImapProvider", "probe", "settings_from"]
