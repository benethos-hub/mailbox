"""Keeping up with the mailboxes: stable message ids, the sync pass
(``SyncService``) and the worker that runs it in the background by
polling and IDLE (``SyncWorker``).
"""

from __future__ import annotations

from .service import SyncService, SyncState
from .worker import Sleep, SyncWorker, WorkerState

__all__ = [
    "Sleep",
    "SyncService",
    "SyncState",
    "SyncWorker",
    "WorkerState",
]
