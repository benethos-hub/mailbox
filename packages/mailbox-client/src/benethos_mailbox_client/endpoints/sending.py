"""Sending: a message at once, or a stored draft, each with the
``Idempotency-Key`` the caller chose, read into ``Sent``. Put into the
outbox instead, sent in the background, each answers its job, an
``OutboxEntry``."""

from __future__ import annotations

from datetime import datetime
from typing import Any

from ..calls import Call, given, path
from ..models import OutboxEntry, Sent
from .outbox import entry


def send_message(
    account_id: str, message: dict[str, Any], idempotency_key: str
) -> Call[Sent]:
    return Call(
        "POST",
        path("accounts", account_id, "send"),
        _sent,
        json=given(message),
        headers={"Idempotency-Key": idempotency_key},
    )


def send_draft(account_id: str, draft_id: str, idempotency_key: str) -> Call[Sent]:
    return Call(
        "POST",
        path("accounts", account_id, "drafts", draft_id, "send"),
        _sent,
        headers={"Idempotency-Key": idempotency_key},
    )


def queue_message(
    account_id: str,
    message: dict[str, Any],
    idempotency_key: str,
    send_at: datetime | None = None,
) -> Call[OutboxEntry]:
    """``send_message`` through the outbox: kept as a draft and sent in the
    background, at ``send_at`` or at once. A provider away does not lose it."""
    return Call(
        "POST",
        path("accounts", account_id, "send"),
        entry,
        json=given({**message, **_queued(send_at)}),
        headers={"Idempotency-Key": idempotency_key},
    )


def queue_draft(
    account_id: str,
    draft_id: str,
    idempotency_key: str,
    send_at: datetime | None = None,
) -> Call[OutboxEntry]:
    """``send_draft`` through the outbox, at ``send_at`` or at once. A
    draft changed or deleted before then is not sent."""
    return Call(
        "POST",
        path("accounts", account_id, "drafts", draft_id, "send"),
        entry,
        json=_queued(send_at),
        headers={"Idempotency-Key": idempotency_key},
    )


def _queued(send_at: datetime | None) -> dict[str, Any]:
    """The fields that put a send into the outbox."""
    found: dict[str, Any] = {"outbox": True}
    if send_at is not None:
        found["send_at"] = send_at.isoformat()
    return found


def _sent(found: dict[str, Any]) -> Sent:
    return Sent(
        message_id_header=str(found["message_id_header"]),
        refused=list(found.get("refused") or []),
        original_marked=found.get("original_marked"),
        sent_copy_id=found.get("sent_copy_id"),
    )
