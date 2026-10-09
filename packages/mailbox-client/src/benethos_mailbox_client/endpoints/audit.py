"""The audit of administration, newest first, read into ``Activity``."""

from __future__ import annotations

from datetime import datetime
from typing import Any

from ..calls import Call, given, path
from ..models import Activity, Paged
from .readings import paged, time


def list_activity(
    *,
    user: str | None = None,
    activity: str | None = None,
    record: str | None = None,
    after: datetime | None = None,
    before: datetime | None = None,
    limit: int | None = None,
    cursor: str | None = None,
) -> Call[Paged[Activity]]:
    """What was done, newest first. ``user`` a user id: what it did.
    ``activity`` a name such as ``users.token_revoked`` or an area such as
    ``webhooks``. ``record`` the id of what was touched. ``after`` and
    ``before`` are times with their zone."""
    return Call(
        "GET",
        path("audit"),
        paged(_activity),
        params=given(
            {
                "user": user,
                "activity": activity,
                "record": record,
                "after": after.isoformat() if after else None,
                "before": before.isoformat() if before else None,
                "limit": limit,
                "cursor": cursor,
            }
        ),
    )


def _activity(item: dict[str, Any]) -> Activity:
    return Activity(
        id=str(item["id"]),
        at=time(item["at"]),
        activity=str(item["activity"]),
        user_id=item.get("user_id"),
        user_name=str(item["user_name"]),
        credential=item.get("credential"),
        record=item.get("record"),
        source=item.get("source"),
        outcome=str(item["outcome"]),
        detail=str(item["detail"]),
    )
