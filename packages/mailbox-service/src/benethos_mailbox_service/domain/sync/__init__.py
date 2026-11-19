"""Keeping up with the mailboxes: stable message ids (``SyncService``),
the sync pass (``SyncRunner``) and the worker that runs it in the
background by polling and IDLE (``SyncWorker``).
"""

from __future__ import annotations

from .runner import SyncState
from .service import SyncService
from .worker import SyncWorker, WorkerState

__all__ = [
    "SyncService",
    "SyncState",
    "SyncWorker",
    "WorkerState",
]
