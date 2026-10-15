"""The messages of one account. Its folders, sending, changes and drafts
are routers of their own.

Two routers, since the routes keep the order of the OpenAPI document:
``router`` stands before sending, ``after_drafts`` after the drafts.
"""

from __future__ import annotations

from typing import Annotated

from fastapi import APIRouter, Query, Response

from ....data.models import (
    BatchResult,
    Message,
    MessageBatch,
    MessageSummary,
    MessageUpdate,
    Page,
    Thread,
    ThreadSummary,
)
from ...responses import download
from ..deps import Caller, Limit, Mailbox, Search

router = APIRouter(prefix="/accounts/{account_id}", tags=["mailbox"])
after_drafts = APIRouter(prefix="/accounts/{account_id}", tags=["mailbox"])


@router.get("/messages")
async def list_messages(
    account_id: str,
    caller: Caller,
    mailbox: Mailbox,
    search: Search,
    folder: Annotated[
        str | None,
        Query(
            description=(
                "A folder id, or a role such as inbox. Left out: the inbox. "
                "The role all lists every folder but the trash and junk, and "
                "answers 501 on an account without such a folder."
            )
        ),
    ] = None,
    limit: Limit = 50,
    cursor: str | None = None,
) -> Page[MessageSummary]:
    """Newest first. The search parameters narrow the list together."""
    return await mailbox.list_messages(
        caller,
        account_id,
        folder_id=folder,
        search=search,
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


@router.get("/threads")
async def list_threads(
    account_id: str,
    caller: Caller,
    mailbox: Mailbox,
    folder: Annotated[str, Query(description="A folder id, or a role such as inbox.")],
    limit: Annotated[int, Query(ge=1, le=50)] = 20,
    cursor: str | None = None,
) -> Page[ThreadSummary]:
    """The threads of a folder, newest first. Each is listed where its
    newest message in the folder is, with what the caller may see of the
    whole thread. A page is a page of the folder's messages, so it may hold
    fewer threads than `limit`. A later page leaves out what an earlier
    one listed. POP3 answers `501`."""
    return await mailbox.list_threads(
        caller, account_id, folder_id=folder, limit=limit, cursor=cursor
    )


@router.get("/threads/{thread_id}")
async def get_thread(
    account_id: str, thread_id: str, caller: Caller, mailbox: Mailbox
) -> Thread:
    """A thread with its messages in every folder, oldest first, those the
    caller may see. A message names its thread in `thread_id`. A longer
    thread lists its newest messages and says `truncated`. POP3 answers
    `501`."""
    return await mailbox.get_thread(caller, account_id, thread_id)


@after_drafts.post("/messages/batch")
async def batch_messages(
    account_id: str, batch: MessageBatch, caller: Caller, mailbox: Mailbox
) -> BatchResult:
    """One action for up to 100 messages, with a result per id. Needs the
    right of the single operation too: `update_message`, `delete_message`
    or, with `permanent`, `delete_message_permanent`."""
    return await mailbox.batch_messages(caller, account_id, batch)


@after_drafts.delete("/messages/{message_id}", status_code=204)
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


@after_drafts.get(
    "/messages/{message_id}/raw",
    response_class=Response,
    responses={200: {"content": {"message/rfc822": {}}, "description": "RFC 822"}},
)
async def get_message_raw(
    account_id: str, message_id: str, caller: Caller, mailbox: Mailbox
) -> Response:
    raw = await mailbox.get_raw(caller, account_id, message_id)
    return Response(content=raw, media_type="message/rfc822")


@after_drafts.get(
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
    return download(
        attachment.data, attachment.filename or attachment_id, attachment.content_type
    )
