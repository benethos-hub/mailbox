"""The change feed of one account. Across accounts it is in ``messages``."""

from __future__ import annotations

from fastapi import APIRouter

from ....data.models import ChangePage
from ..deps import Caller, Limit, Mailbox, Since
from ..errors import CHANGES_ERRORS

router = APIRouter(prefix="/accounts/{account_id}", tags=["mailbox"])


@router.get("/changes", responses=CHANGES_ERRORS)
async def list_changes(
    account_id: str,
    caller: Caller,
    mailbox: Mailbox,
    since: Since = None,
    limit: Limit = 100,
) -> ChangePage:
    """Messages created, updated or deleted in this account since `since`,
    oldest first, ids only. Ask again with the answer's `state` for the
    next ones. Without `since`, start from the current state."""
    return await mailbox.list_changes(caller, account_id, since=since, limit=limit)
