"""The audit of administration (docs/AUDIT.md)."""

from __future__ import annotations

from typing import Annotated

from fastapi import APIRouter, Query
from pydantic import AwareDatetime

from ....data.models import ActivityFilter, ActivityRecord, Page
from ...services import Activities
from ..deps import Caller, Limit

router = APIRouter(prefix="/audit", tags=["audit"])


@router.get("")
async def list_activity(
    caller: Caller,
    audit: Activities,
    user: Annotated[
        str | None, Query(description="A user id: what that user did")
    ] = None,
    activity: Annotated[
        str | None,
        Query(
            description=(
                "A name such as `users.token_revoked`, or an area such as `users`"
            )
        ),
    ] = None,
    record: Annotated[
        str | None,
        Query(
            description=(
                "The id of a user, token, role, account or webhook: what was done to it"
            )
        ),
    ] = None,
    after: Annotated[
        AwareDatetime | None,
        Query(
            description="At or after this time: ISO 8601 with a zone, "
            "e.g. 2026-09-01T00:00:00+02:00"
        ),
    ] = None,
    before: Annotated[
        AwareDatetime | None,
        Query(description="Before this time: ISO 8601 with a zone"),
    ] = None,
    limit: Limit = 50,
    cursor: str | None = None,
) -> Page[ActivityRecord]:
    """The audit of administration, newest first: sign-ins, and who
    changed users, tokens, roles, accounts and webhooks, kept for
    `MAILBOX_SERVICE_AUDIT_DAYS` days. Never a secret, never mail content.
    Needs `audit` in `service`."""
    wanted = {
        "user_id": user,
        "activity": activity,
        "record": record,
        "after": after,
        "before": before,
    }
    matching = (
        ActivityFilter.model_validate(wanted)
        if any(value is not None for value in wanted.values())
        else None
    )
    return audit.list_activity(caller, limit=limit, cursor=cursor, matching=matching)
