"""The drafts of an account: listed, written, replaced and deleted. A
draft is read as a message is. Its body on the way in is made by
``compose``."""

from __future__ import annotations

from typing import Any

from ..calls import Call, given, nothing, path
from ..models import MessageSummary, Page
from .messages import page, summary


def list_drafts(account_id: str, limit: int, cursor: str | None = None) -> Call[Page]:
    return Call(
        "GET",
        path("accounts", account_id, "drafts"),
        page,
        params=given({"limit": limit, "cursor": cursor}),
    )


def create_draft(account_id: str, message: dict[str, Any]) -> Call[MessageSummary]:
    """Takes ``message`` as ``message_body`` makes it. Answers the draft's
    summary."""
    return Call(
        "POST", path("accounts", account_id, "drafts"), summary, json=given(message)
    )


def update_draft(
    account_id: str,
    draft_id: str,
    message: dict[str, Any],
    keep_attachments: list[str] | None = None,
) -> Call[MessageSummary]:
    """``keep_attachments``: ids of the stored draft's attachments that
    stay. None or empty: none of them. Answers the draft's summary."""
    return Call(
        "PUT",
        path("accounts", account_id, "drafts", draft_id),
        summary,
        json=given({**message, "keep_attachments": keep_attachments or None}),
    )


def delete_draft(account_id: str, draft_id: str) -> Call[None]:
    return Call("DELETE", path("accounts", account_id, "drafts", draft_id), nothing)
