"""Mail accounts: connect, change, verify and delete them under the
caller's rights (``AccountService``), the live adapter of each
(``Adapters``), and connecting by OAuth (``OAuthService``).
"""

from __future__ import annotations

from .abilities import deletes, deltas, drafts, sends, watches, writes
from .adapters import Adapters
from .oauth import DeviceSignIn, OAuthService
from .service import AccountService

__all__ = [
    "AccountService",
    "Adapters",
    "DeviceSignIn",
    "OAuthService",
    "deletes",
    "deltas",
    "drafts",
    "sends",
    "watches",
    "writes",
]
