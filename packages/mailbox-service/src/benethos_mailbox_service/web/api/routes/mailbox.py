"""Folders and messages of one account."""

from __future__ import annotations

from typing import Annotated, Any

from fastapi import APIRouter, Header, Query, Response

from ....data.models import (
    BatchResult,
    ChangePage,
    DraftMessage,
    Folder,
    FolderCreate,
    FolderUpdate,
    Message,
    MessageBatch,
    MessageSummary,
    MessageUpdate,
    OutgoingMessage,
    Page,
    SendRecord,
    SendResult,
)
from ...responses import download
from ..deps import Caller, Limit, Mailbox, Search, Since
from ..errors import CHANGES_ERRORS
from ..schemas import DraftReplacement, ErrorResponse

router = APIRouter(prefix="/accounts/{account_id}", tags=["mailbox"])

# A grant may narrow sending (CONCEPT 7.5).
SEND_ERRORS: dict[int | str, dict[str, Any]] = {
    403: {
        "model": ErrorResponse,
        "description": (
            "The caller lacks the right, or no grant allows these recipients "
            "(`recipient_not_allowed`)"
        ),
    },
    429: {
        "model": ErrorResponse,
        "description": "The grant's send limit is reached (`send_limit_reached`), "
        "see Retry-After",
    },
}


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
    """Rename or move a folder. On IMAP its id follows its name and changes,
    but the messages inside keep theirs. Folders with a role answer `409`."""
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
    search: Search,
    folder: Annotated[
        str | None,
        Query(
            description=(
                "A folder id, or a role such as inbox. Left out: every folder "
                "on a Microsoft account, the inbox on IMAP."
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


IdempotencyKey = Annotated[
    str | None,
    Header(
        alias="Idempotency-Key",
        min_length=1,
        max_length=200,
        description=(
            "Sent again with the same key within 24 hours, the request "
            "returns the first result instead of sending twice. The same "
            "key with a different message answers `409`."
        ),
    ),
]


@router.post("/send", responses=SEND_ERRORS)
async def send_message(
    account_id: str,
    message: OutgoingMessage,
    caller: Caller,
    mailbox: Mailbox,
    idempotency_key: IdempotencyKey = None,
) -> SendResult:
    """Send from the account's address. The service sets From, Date and
    Message-ID and keeps a read copy in the sent folder. `200` means the
    mail server accepted the message. It cannot be taken back."""
    return await mailbox.send_message(caller, account_id, message, idempotency_key)


@router.get("/sends")
async def list_sends(
    account_id: str,
    caller: Caller,
    mailbox: Mailbox,
    limit: Limit = 50,
    cursor: str | None = None,
) -> Page[SendRecord]:
    """The audit of sends from this account, newest first: every attempt
    through `send_message` or `send_draft`, sent, denied by a grant or
    failed, with user, token and recipients, never content."""
    return mailbox.list_sends(caller, account_id, limit=limit, cursor=cursor)


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
    return mailbox.list_changes(caller, account_id, since=since, limit=limit)


@router.get("/drafts")
async def list_drafts(
    account_id: str,
    caller: Caller,
    mailbox: Mailbox,
    limit: Limit = 50,
    cursor: str | None = None,
) -> Page[MessageSummary]:
    """The drafts, newest first. A draft id is a message id and reads with
    `get_message`."""
    return await mailbox.list_drafts(caller, account_id, limit=limit, cursor=cursor)


@router.post("/drafts", status_code=201)
async def create_draft(
    account_id: str, draft: DraftMessage, caller: Caller, mailbox: Mailbox
) -> MessageSummary:
    """Store a draft in the drafts folder, composed as `send_message` would,
    recipients optional. With a `reference` the quote is added now, and it
    needs `get_message` too."""
    return await mailbox.create_draft(caller, account_id, draft)


@router.put("/drafts/{draft_id}")
async def update_draft(
    account_id: str,
    draft_id: str,
    draft: DraftReplacement,
    caller: Caller,
    mailbox: Mailbox,
) -> MessageSummary:
    """Replace a draft as a whole. Its id stays. Stored attachments are
    gone unless `keep_attachments` names them. An id that names no draft
    answers `404`."""
    return await mailbox.update_draft(
        caller,
        account_id,
        draft_id,
        DraftMessage.model_validate(draft, from_attributes=True),
        keep_attachments=draft.keep_attachments,
    )


@router.post("/drafts/{draft_id}/send", responses=SEND_ERRORS)
async def send_draft(
    account_id: str,
    draft_id: str,
    caller: Caller,
    mailbox: Mailbox,
    idempotency_key: IdempotencyKey = None,
) -> SendResult:
    """Send a draft as it is stored, dated now. Then it is deleted and a
    read copy kept in the sent folder. A reply or forward marks its
    original. Right: `send_draft` (`send`). It cannot be taken back."""
    return await mailbox.send_draft(caller, account_id, draft_id, idempotency_key)


@router.delete("/drafts/{draft_id}", status_code=204)
async def delete_draft(
    account_id: str, draft_id: str, caller: Caller, mailbox: Mailbox
) -> None:
    """Delete a draft for good. An id that names no draft answers `404`."""
    await mailbox.delete_draft(caller, account_id, draft_id)


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
    return download(
        attachment.data, attachment.filename or attachment_id, attachment.content_type
    )
