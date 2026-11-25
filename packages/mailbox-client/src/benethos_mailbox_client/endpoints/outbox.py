"""The outbox of one account: its sends, one of them, and cancelling one
that waits, read into ``OutboxEntry``."""

from __future__ import annotations

from typing import Any

from ..calls import Call, given, path
from ..models import OutboxEntry, Paged
from .readings import maybe_time, paged, time


def list_outbox(
    account_id: str,
    *,
    state: str | None = None,
    limit: int | None = None,
    cursor: str | None = None,
) -> Call[Paged[OutboxEntry]]:
    """The sends of the outbox the caller may see, newest first. ``state``
    narrows them, such as ``queued`` or ``failed``."""
    return Call(
        "GET",
        path("accounts", account_id, "outbox"),
        paged(entry),
        params=given({"state": state, "limit": limit, "cursor": cursor}),
    )


def get_outbox_job(account_id: str, job_id: str) -> Call[OutboxEntry]:
    return Call("GET", path("accounts", account_id, "outbox", job_id), entry)


def cancel_send(account_id: str, job_id: str) -> Call[OutboxEntry]:
    """Cancel a send that waits. Its draft stays."""
    return Call("DELETE", path("accounts", account_id, "outbox", job_id), entry)


def entry(found: dict[str, Any]) -> OutboxEntry:
    return OutboxEntry(
        id=str(found["id"]),
        account_id=str(found["account_id"]),
        user_id=str(found["user_id"]),
        operation=str(found["operation"]),
        draft_id=str(found["draft_id"]),
        message_id_header=str(found["message_id_header"]),
        recipients=list(found.get("recipients") or []),
        state=str(found["state"]),
        attempts=int(found.get("attempts") or 0),
        due_at=time(found["due_at"]),
        expires_at=time(found["expires_at"]),
        send_at=maybe_time(found.get("send_at")),
        last_error=found.get("last_error"),
        created_at=time(found["created_at"]),
        finished_at=maybe_time(found.get("finished_at")),
    )
