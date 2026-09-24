"""Folders and messages of one account."""

from __future__ import annotations

from typing import Annotated

from fastapi import APIRouter, Query

from ...data.models import Folder, Message, MessageSummary, Page
from ..deps import Mailbox

router = APIRouter(prefix="/accounts/{account_id}", tags=["mailbox"])


@router.get("/folders")
async def list_folders(account_id: str, mailbox: Mailbox) -> list[Folder]:
    return await mailbox.list_folders(account_id)


@router.get("/messages")
async def list_messages(
    account_id: str,
    mailbox: Mailbox,
    folder: Annotated[str | None, Query(description="Folder id")] = None,
    q: Annotated[str | None, Query(description="Search text")] = None,
    unread: bool | None = None,
    limit: Annotated[int, Query(ge=1, le=200)] = 50,
    cursor: str | None = None,
) -> Page[MessageSummary]:
    return await mailbox.list_messages(
        account_id,
        folder_id=folder,
        query=q,
        unread=unread,
        limit=limit,
        cursor=cursor,
    )


@router.get("/messages/{message_id}")
async def get_message(account_id: str, message_id: str, mailbox: Mailbox) -> Message:
    return await mailbox.get_message(account_id, message_id)
