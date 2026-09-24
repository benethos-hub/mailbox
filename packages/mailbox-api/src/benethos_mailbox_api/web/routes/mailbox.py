"""Folders and messages of one account."""

from __future__ import annotations

from typing import Annotated
from urllib.parse import quote

from fastapi import APIRouter, Query, Response

from ...data.models import Folder, Message, MessageSummary, Page
from ..deps import Caller, Mailbox

router = APIRouter(prefix="/accounts/{account_id}", tags=["mailbox"])


@router.get("/folders")
async def list_folders(
    account_id: str, caller: Caller, mailbox: Mailbox
) -> list[Folder]:
    return await mailbox.list_folders(caller, account_id)


@router.get("/messages")
async def list_messages(
    account_id: str,
    caller: Caller,
    mailbox: Mailbox,
    folder: Annotated[str | None, Query(description="Folder id")] = None,
    q: Annotated[str | None, Query(description="Search text")] = None,
    unread: bool | None = None,
    limit: Annotated[int, Query(ge=1, le=200)] = 50,
    cursor: str | None = None,
) -> Page[MessageSummary]:
    return await mailbox.list_messages(
        caller,
        account_id,
        folder_id=folder,
        query=q,
        unread=unread,
        limit=limit,
        cursor=cursor,
    )


@router.get("/messages/{message_id}")
async def get_message(
    account_id: str, message_id: str, caller: Caller, mailbox: Mailbox
) -> Message:
    return await mailbox.get_message(caller, account_id, message_id)


@router.get(
    "/messages/{message_id}/raw",
    response_class=Response,
    responses={200: {"content": {"message/rfc822": {}}, "description": "RFC 822"}},
)
async def get_message_raw(
    account_id: str, message_id: str, caller: Caller, mailbox: Mailbox
) -> Response:
    raw = await mailbox.get_raw(caller, account_id, message_id)
    return Response(content=raw, media_type="message/rfc822")


@router.get(
    "/messages/{message_id}/attachments/{attachment_id}",
    response_class=Response,
    responses={
        200: {"content": {"application/octet-stream": {}}, "description": "Content"}
    },
)
async def get_attachment(
    account_id: str,
    message_id: str,
    attachment_id: str,
    caller: Caller,
    mailbox: Mailbox,
) -> Response:
    attachment = await mailbox.get_attachment(
        caller, account_id, message_id, attachment_id
    )
    filename = attachment.filename or attachment_id
    return Response(
        content=attachment.data,
        media_type=attachment.content_type,
        headers={
            "Content-Disposition": f"attachment; filename*=UTF-8''{quote(filename)}"
        },
    )
