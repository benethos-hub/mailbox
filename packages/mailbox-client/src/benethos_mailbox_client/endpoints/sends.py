"""The audit of sends, of one account or across every account the
caller may audit, newest first, read into ``SendRecord``."""

from __future__ import annotations

from datetime import datetime
from typing import Any

from ..calls import Call, given, path
from ..models import Paged, SendRecord
from .readings import paged, time


def list_sends(
    account_id: str,
    *,
    user: str | None = None,
    outcome: str | None = None,
    recipient: str | None = None,
    after: datetime | None = None,
    before: datetime | None = None,
    limit: int | None = None,
    cursor: str | None = None,
) -> Call[Paged[SendRecord]]:
    """The sends of one account. ``user`` a user id, ``outcome`` ``sent``,
    ``denied`` or ``failed``, ``recipient`` a part of an address."""
    return Call(
        "GET",
        path("accounts", account_id, "sends"),
        paged(_send),
        params=_filters(user, outcome, recipient, after, before, limit, cursor),
    )


def list_all_sends(
    *,
    accounts: list[str] | None = None,
    user: str | None = None,
    outcome: str | None = None,
    recipient: str | None = None,
    after: datetime | None = None,
    before: datetime | None = None,
    limit: int | None = None,
    cursor: str | None = None,
) -> Call[Paged[SendRecord]]:
    """The sends of every account the caller may audit, or of those in
    ``accounts``, the filters as ``list_sends`` takes them."""
    return Call(
        "GET",
        path("sends"),
        paged(_send),
        params={
            **given({"accounts": accounts}),
            **_filters(user, outcome, recipient, after, before, limit, cursor),
        },
    )


def _filters(
    user: str | None,
    outcome: str | None,
    recipient: str | None,
    after: datetime | None,
    before: datetime | None,
    limit: int | None,
    cursor: str | None,
) -> dict[str, Any]:
    return given(
        {
            "user": user,
            "outcome": outcome,
            "recipient": recipient,
            "after": after.isoformat() if after else None,
            "before": before.isoformat() if before else None,
            "limit": limit,
            "cursor": cursor,
        }
    )


def _send(item: dict[str, Any]) -> SendRecord:
    return SendRecord(
        id=str(item["id"]),
        created_at=time(item["created_at"]),
        user_id=str(item["user_id"]),
        credential_id=item.get("credential_id"),
        account_id=str(item["account_id"]),
        operation=str(item["operation"]),
        recipients=tuple(item["recipients"]),
        outcome=str(item["outcome"]),
        error=item.get("error"),
        refused=tuple(item.get("refused") or []),
        message_id_header=item.get("message_id_header"),
    )
