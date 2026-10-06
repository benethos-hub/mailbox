"""Draft tools: list, write, replace and delete drafts. Nothing is sent."""

from __future__ import annotations

from typing import Annotated, Any

from pydantic import Field

from .. import render
from .base import MAX_LIMIT, changes, client, reads
from .compose import Action, Addresses, Html, OriginalId, Text, composed


async def list_drafts(
    account_id: str,
    limit: Annotated[int, Field(ge=1, le=MAX_LIMIT)] = 20,
    cursor: Annotated[
        str | None, Field(description="next_cursor of the previous call")
    ] = None,
) -> dict[str, Any]:
    """The drafts of an account, newest first. get_message reads one by
    its id."""
    page = await client().list_drafts(account_id, limit, cursor)
    return {
        "drafts": [render.draft(item) for item in page.items],
        "next_cursor": page.next_cursor,
        "note": render.DRAFTS_NOTE,
    }


async def create_draft(
    account_id: str,
    to: Addresses = None,
    cc: Addresses = None,
    bcc: Addresses = None,
    subject: str = "",
    text: Text = "",
    html: Html = None,
    original_id: OriginalId = None,
    action: Action = "reply",
) -> dict[str, Any]:
    """Write a draft into the drafts folder. Nothing is sent. With
    original_id it answers or forwards that message: the service adds
    recipients of a reply, the subject prefix and the quote. Recipients may
    stay empty."""
    body = composed(to, cc, bcc, subject, text, html, original_id, action)
    return render.draft(await client().create_draft(account_id, body))


async def update_draft(
    account_id: str,
    draft_id: str,
    to: Addresses = None,
    cc: Addresses = None,
    bcc: Addresses = None,
    subject: str = "",
    text: Text = "",
    html: Html = None,
    original_id: OriginalId = None,
    action: Action = "reply",
    keep_attachments: Annotated[
        list[str] | None,
        Field(description="Ids of the stored draft's attachments to keep"),
    ] = None,
) -> dict[str, Any]:
    """Replace a draft as a whole: what is left out is gone afterwards,
    attachments too unless keep_attachments names them. Read it with
    get_message first to keep parts of it. Use the id it answers with from
    now on: some providers store the draft under a new one."""
    body = composed(to, cc, bcc, subject, text, html, original_id, action)
    return render.draft(
        await client().update_draft(account_id, draft_id, body, keep_attachments)
    )


async def delete_draft(account_id: str, draft_id: str) -> str:
    """Delete a draft for good. Reaches drafts only, never other mail."""
    await client().delete_draft(account_id, draft_id)
    return f"draft {draft_id} deleted"


TOOLS = (
    reads(list_drafts, "List drafts", "list_drafts", kind="drafts"),
    changes(
        create_draft,
        "Write a draft",
        "drafts",
        "create_draft",
        destructive=False,
        idempotent=False,
    ),
    # Replaces the draft as a whole, under the same id.
    changes(
        update_draft,
        "Replace a draft",
        "drafts",
        "update_draft",
        destructive=True,
        idempotent=True,
    ),
    changes(
        delete_draft,
        "Delete a draft",
        "drafts",
        "delete_draft",
        destructive=True,
        idempotent=True,
    ),
)
