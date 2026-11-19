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
from .connections import connection_of, connections, takes_server_name
from .device import DeviceSignIn
from .oauth import OAuthService
from .service import AccountHooks, AccountService, Rename, SeenName, SeenNames

__all__ = [
    "NEEDS",
    "AccountHooks",
    "AccountService",
    "Rename",
    "SeenName",
    "SeenNames",
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
    "connection_of",
    "takes_server_name",
    "connections",
]
