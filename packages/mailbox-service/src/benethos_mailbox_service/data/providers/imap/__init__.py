"""The IMAP provider, registry key ``imap``."""

from __future__ import annotations

from .connect import probe, settings_from
from .provider import ImapProvider

__all__ = ["ImapProvider", "probe", "settings_from"]
