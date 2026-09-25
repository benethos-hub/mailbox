"""Messages and changes across accounts."""

from __future__ import annotations

from typing import Annotated

from fastapi import APIRouter, Query

from ....data.models import ChangePage, FolderRole, MessagePage
from ..deps import Caller, Limit, Mailbox, Search, Since
from ..errors import CHANGES_ERRORS

router = APIRouter(tags=["mailbox"])


@router.get("/messages")
async def list_all_messages(
    caller: Caller,
    mailbox: Mailbox,
    search: Search,
    accounts: Annotated[
        list[str] | None,
        Query(description="Account ids. Without: every account the caller may read"),
    ] = None,
    folder: Annotated[
        FolderRole | None, Query(description="A folder role, e.g. inbox")
    ] = None,
    limit: Limit = 50,
    cursor: str | None = None,
) -> MessagePage:
    return await mailbox.list_all_messages(
        caller,
        account_ids=accounts,
        folder_role=folder,
        search=search,
        limit=limit,
        cursor=cursor,
    )


@router.get("/changes", responses=CHANGES_ERRORS)
async def list_all_changes(
    caller: Caller,
    mailbox: Mailbox,
    accounts: Annotated[
        list[str] | None,
        Query(description="Account ids. Without: every account the caller may read"),
    ] = None,
    since: Since = None,
    limit: Limit = 100,
) -> ChangePage:
    """Messages created, updated or deleted since `since` in every account
    the caller may read, oldest first, ids only. The state is the same
    point as in the feed of one account."""
    return mailbox.list_all_changes(
        caller, account_ids=accounts, since=since, limit=limit
    )
