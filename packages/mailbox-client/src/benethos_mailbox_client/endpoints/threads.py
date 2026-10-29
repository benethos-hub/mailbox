"""Threads: those of a folder, and one with its messages, read into
``ThreadSummary`` and ``Thread``."""

from __future__ import annotations

from typing import Any

from ..calls import Call, given, path
from ..models import Paged, Thread, ThreadSummary
from .messages import addresses, summary
from .readings import maybe_time, paged


def list_threads(
    account_id: str,
    *,
    folder: str,
    limit: int | None = None,
    cursor: str | None = None,
) -> Call[Paged[ThreadSummary]]:
    """The threads of a folder, newest first. ``folder`` is an id or a
    role. A page may hold fewer threads than ``limit``."""
    return Call(
        "GET",
        path("accounts", account_id, "threads"),
        paged(_summary),
        params=given({"folder": folder, "limit": limit, "cursor": cursor}),
    )


def get_thread(account_id: str, thread_id: str) -> Call[Thread]:
    """A thread with its messages, oldest first. A message names its
    thread in ``thread_id``."""
    return Call("GET", path("accounts", account_id, "threads", thread_id), _thread)


def _fields(found: dict[str, Any]) -> dict[str, Any]:
    return {
        "id": str(found["id"]),
        "account_id": str(found["account_id"]),
        "subject": found.get("subject"),
        "participants": addresses(found.get("participants")),
        "message_count": int(found["message_count"]),
        "unread_count": int(found["unread_count"]),
        "date": maybe_time(found.get("date")),
        "snippet": found.get("snippet"),
        "folder_ids": [str(f) for f in found.get("folder_ids") or []],
        "truncated": bool(found.get("truncated")),
    }


def _summary(found: dict[str, Any]) -> ThreadSummary:
    return ThreadSummary(**_fields(found))


def _thread(found: dict[str, Any]) -> Thread:
    return Thread(
        **_fields(found), messages=[summary(m) for m in found.get("messages") or []]
    )
