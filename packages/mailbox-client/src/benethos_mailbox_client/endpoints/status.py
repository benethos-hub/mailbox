"""The state of the service, read into ``Status``."""

from __future__ import annotations

from typing import Any

from ..calls import Call, path
from ..models import AccountHealth, Status, Worker
from .readings import maybe_time


def get_status() -> Call[Status]:
    """The sync worker and the accounts the caller may see the status of.
    Kept in memory: empty after a restart until the first pass."""
    return Call("GET", path("status"), _status)


def _status(found: dict[str, Any]) -> Status:
    worker = found.get("worker")
    return Status(
        worker=(
            Worker(
                interval=float(worker["interval"]),
                push=bool(worker["push"]),
                last_pass_at=maybe_time(worker.get("last_pass_at")),
                watchers=int(worker["watchers"]),
                watching=int(worker["watching"]),
            )
            if worker
            else None
        ),
        accounts=tuple(
            AccountHealth(
                id=str(a["id"]),
                email=str(a["email"]),
                provider=str(a["provider"]),
                status=str(a["status"]),
                synced=bool(a["synced"]),
                watching=bool(a["watching"]),
                last_sync_at=maybe_time(a.get("last_sync_at")),
                last_error=a.get("last_error"),
                last_error_at=maybe_time(a.get("last_error_at")),
                attention=bool(a["attention"]),
            )
            for a in found["accounts"]
        ),
    )
