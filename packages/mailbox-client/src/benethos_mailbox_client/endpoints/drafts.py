"""The drafts of an account: listed, written, replaced and deleted. A
draft is the JSON of the API, as a message is; its body on the way in is
made by ``compose``."""

from __future__ import annotations

from typing import Any

from ..calls import Call, given, nothing, path
from ..models import Page
from .messages import page


def list_drafts(account_id: str, limit: int, cursor: str | None) -> Call[Page]:
    return Call(
        "GET",
        path("accounts", account_id, "drafts"),
        page,
        params=given({"limit": limit, "cursor": cursor}),
    )


def create_draft(account_id: str, message: dict[str, Any]) -> Call[dict[str, Any]]:
    """Takes ``message`` as ``message_body`` makes it. Answers the draft's
    summary."""
    return Call(
        "POST", path("accounts", account_id, "drafts"), dict, json=given(message)
    )


def update_draft(
    account_id: str,
    draft_id: str,
    message: dict[str, Any],
    keep_attachments: list[str] | None = None,
) -> Call[dict[str, Any]]:
    """``keep_attachments``: ids of the stored draft's attachments that
    stay. None or empty: none of them."""
    return Call(
        "PUT",
        path("accounts", account_id, "drafts", draft_id),
        dict,
        json=given({**message, "keep_attachments": keep_attachments or None}),
    )


def delete_draft(account_id: str, draft_id: str) -> Call[None]:
    return Call("DELETE", path("accounts", account_id, "drafts", draft_id), nothing)
