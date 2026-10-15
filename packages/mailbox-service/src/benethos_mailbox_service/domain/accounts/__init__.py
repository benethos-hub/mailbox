"""Mail accounts: connect, change, verify and delete them under the
caller's rights (``AccountService``), the live adapter of each
(``Adapters``), and connecting by OAuth (``OAuthService``).
"""

from __future__ import annotations

from .abilities import (
    NEEDS,
    Needs,
    deletes,
    deltas,
    drafts,
    for_delete,
    for_list,
    for_update,
    of_account,
    operations,
    sends,
    summaries,
    threads,
    watches,
    writes,
)
from .adapters import Adapters
from .device import DeviceSignIn
from .oauth import OAuthService
from .service import AccountService

__all__ = [
    "NEEDS",
    "AccountService",
    "Adapters",
    "DeviceSignIn",
    "Needs",
    "OAuthService",
    "deletes",
    "deltas",
    "drafts",
    "for_delete",
    "for_list",
    "for_update",
    "of_account",
    "operations",
    "sends",
    "summaries",
    "threads",
    "watches",
    "writes",
]
