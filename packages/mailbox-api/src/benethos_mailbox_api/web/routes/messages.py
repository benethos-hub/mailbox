"""Messages across accounts."""

from __future__ import annotations

from typing import Annotated

from fastapi import APIRouter, Query

from ...data.models import FolderRole, MessagePage
from ..deps import Caller, Mailbox

router = APIRouter(tags=["mailbox"])


@router.get("/messages")
async def list_all_messages(
    caller: Caller,
    mailbox: Mailbox,
    accounts: Annotated[
        list[str] | None,
        Query(description="Account ids. Without: every account the caller may read"),
    ] = None,
    folder: Annotated[
        FolderRole | None, Query(description="A folder role, e.g. inbox")
    ] = None,
    q: Annotated[str | None, Query(description="Search text")] = None,
    unread: bool | None = None,
    limit: Annotated[int, Query(ge=1, le=200)] = 50,
    cursor: str | None = None,
) -> MessagePage:
    return await mailbox.list_all_messages(
        caller,
        account_ids=accounts,
        folder_role=folder,
        query=q,
        unread=unread,
        limit=limit,
        cursor=cursor,
    )
