"""Sending: a message at once, or a stored draft, each with the
``Idempotency-Key`` the caller chose, read into ``Sent``."""

from __future__ import annotations

from typing import Any

from ..calls import Call, given, path
from ..models import Sent


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


def _sent(found: dict[str, Any]) -> Sent:
    return Sent(
        message_id_header=found.get("message_id_header"),
        refused=list(found.get("refused") or []),
    )
