"""Microsoft 365 and Outlook.com over Microsoft Graph, registry key
``microsoft``."""

from __future__ import annotations

from .provider import MicrosoftProvider
from .signin import CLIENT_ID, endpoints

__all__ = ["CLIENT_ID", "MicrosoftProvider", "endpoints"]
