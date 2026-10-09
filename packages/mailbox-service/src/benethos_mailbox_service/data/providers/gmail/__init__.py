"""Gmail and Google Workspace over the Gmail API, registry key ``gmail``."""

from __future__ import annotations

from .provider import GmailProvider
from .signin import endpoints

__all__ = ["GmailProvider", "endpoints"]
