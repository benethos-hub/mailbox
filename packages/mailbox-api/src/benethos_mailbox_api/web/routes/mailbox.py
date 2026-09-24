"""Folders and messages of one account."""

from __future__ import annotations

from typing import Annotated
from urllib.parse import quote

from fastapi import APIRouter, Query, Response

from ...data.models import (
    BatchResult,
    Folder,
    FolderCreate,
    FolderUpdate,
    Message,
    MessageBatch,
    MessageSummary,
    MessageUpdate,
    OutgoingMessage,
    Page,
    SendResult,
)
from ..deps import Caller, Mailbox

router = APIRouter(prefix="/accounts/{account_id}", tags=["mailbox"])


@router.get("/folders")
async def list_folders(
    account_id: str, caller: Caller, mailbox: Mailbox
) -> list[Folder]:
    return await mailbox.list_folders(caller, account_id)


@router.post("/folders", status_code=201)
async def create_folder(
    account_id: str, new: FolderCreate, caller: Caller, mailbox: Mailbox
) -> Folder:
    """Create a folder, subscribed so that mail clients show it."""
    return await mailbox.create_folder(caller, account_id, new)


@router.patch("/folders/{folder_id}")
async def update_folder(
    account_id: str,
    folder_id: str,
    changes: FolderUpdate,
    caller: Caller,
    mailbox: Mailbox,
) -> Folder:
    """Rename or move a folder. On IMAP its id follows its name and changes;
    the messages inside keep theirs. Folders with a role answer `409`."""
    return await mailbox.update_folder(caller, account_id, folder_id, changes)


@router.delete("/folders/{folder_id}", status_code=204)
async def delete_folder(
    account_id: str, folder_id: str, caller: Caller, mailbox: Mailbox
) -> None:
    """Delete an empty folder without subfolders. Anything else answers
    `409`, as do folders with a role."""
    await mailbox.delete_folder(caller, account_id, folder_id)


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


@router.patch("/messages/{message_id}")
async def update_message(
    account_id: str,
    message_id: str,
    changes: MessageUpdate,
    caller: Caller,
    mailbox: Mailbox,
) -> MessageSummary:
    """Mark read or unread, star, set keywords. Fields left out stay."""
    return await mailbox.update_message(caller, account_id, message_id, changes)


@router.post("/send")
async def send_message(
    account_id: str, message: OutgoingMessage, caller: Caller, mailbox: Mailbox
) -> SendResult:
    """Send from the account's address. The service sets From, Date and
    Message-ID and keeps a read copy in the sent folder. `200` means the
    mail server accepted the message; it cannot be taken back."""
    return await mailbox.send_message(caller, account_id, message)


@router.post("/messages/batch")
async def batch_messages(
    account_id: str, batch: MessageBatch, caller: Caller, mailbox: Mailbox
) -> BatchResult:
    """One action for up to 100 messages, with a result per id. Needs the
    right of the single operation too: `update_message`, `delete_message`
    or, with `permanent`, `delete_message_permanent`."""
    return await mailbox.batch_messages(caller, account_id, batch)


@router.delete("/messages/{message_id}", status_code=204)
async def delete_message(
    account_id: str,
    message_id: str,
    caller: Caller,
    mailbox: Mailbox,
    permanent: Annotated[
        bool,
        Query(
            description=(
                "Delete for good instead of moving into the trash. Needs the "
                "right `delete_message_permanent` (`mail.delete`)."
            )
        ),
    ] = False,
) -> None:
    """Into the trash. A message already there answers `409`: delete it
    with `permanent=true`."""
    await mailbox.delete_message(caller, account_id, message_id, permanent)


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
