"""Messages: listed and searched in one account or across every account
the caller may read, the changes since a state, one message, an
attachment, flags and moves for many at once, deleting. The page of
summaries is read here for the drafts as well."""

from __future__ import annotations

from typing import Any

from ..calls import ATTACHMENT_TIMEOUT, Call, as_is, given, nothing, path
from ..models import Changes, Outcome, Page


def list_messages(
    account_id: str | None,
    *,
    folder: str | None = None,
    text: str | None = None,
    sender: str | None = None,
    to: str | None = None,
    subject: str | None = None,
    after: str | None = None,
    before: str | None = None,
    unread: bool | None = None,
    starred: bool | None = None,
    has_attachments: bool | None = None,
    limit: int,
    cursor: str | None = None,
) -> Call[Page]:
    """One account's messages, or with ``account_id`` None, those of
    every account the caller may read. ``folder`` is an id or a role.
    Across accounts it must be a role."""
    return Call(
        "GET",
        _scoped(account_id, "messages"),
        page,
        params=given(
            {
                "folder": folder,
                "q": text,
                "from": sender,
                "to": to,
                "subject": subject,
                "after": after,
                "before": before,
                "unread": unread,
                "starred": starred,
                "has_attachments": has_attachments,
                "limit": limit,
                "cursor": cursor,
            }
        ),
    )


def list_changes(
    account_id: str | None, *, since: str | None, limit: int
) -> Call[Changes]:
    """The changes of one account, or with ``account_id`` None, of every
    account the caller may read, after the point ``since``."""
    return Call(
        "GET",
        _scoped(account_id, "changes"),
        _changes,
        params=given({"since": since, "limit": limit}),
    )


def get_message(account_id: str, message_id: str) -> Call[dict[str, Any]]:
    return Call("GET", path("accounts", account_id, "messages", message_id), dict)


def get_attachment(account_id: str, message_id: str, attachment_id: str) -> Call[Any]:
    """The attachment's bytes. Read as a stream, not as JSON."""
    return Call(
        "GET",
        path(
            "accounts", account_id, "messages", message_id, "attachments", attachment_id
        ),
        as_is,
        timeout=ATTACHMENT_TIMEOUT,
    )


def update_messages(
    account_id: str,
    message_ids: list[str],
    *,
    unread: bool | None = None,
    starred: bool | None = None,
    folder_id: str | None = None,
) -> Call[Outcome]:
    """Flags and a move for many messages at once. ``folder_id`` may be
    a role such as ``archive``."""
    changes: dict[str, Any] = {"unread": unread, "starred": starred}
    if folder_id is not None:
        changes["folder_ids"] = [folder_id]
    return _batch(
        account_id, {"ids": message_ids, "action": "update", "changes": given(changes)}
    )


def delete_message(
    account_id: str, message_id: str, *, permanent: bool = False
) -> Call[None]:
    """Into the trash, or with ``permanent`` for good."""
    return Call(
        "DELETE",
        path("accounts", account_id, "messages", message_id),
        nothing,
        params=given({"permanent": permanent or None}),
    )


def trash_messages(account_id: str, message_ids: list[str]) -> Call[Outcome]:
    return _batch(account_id, {"ids": message_ids, "action": "delete"})


def _batch(account_id: str, body: dict[str, Any]) -> Call[Outcome]:
    return Call(
        "POST",
        path("accounts", account_id, "messages", "batch"),
        _outcome,
        json=given(body),
    )


def _scoped(account_id: str | None, what: str) -> str:
    """``what`` of one account, or with ``account_id`` None, of every
    account the caller may use."""
    return path("accounts", account_id, what) if account_id else path(what)


# --- the readings ---------------------------------------------------------------------


def page(found: dict[str, Any]) -> Page:
    """A page of summaries, of messages or of drafts."""
    return Page(
        items=list(found.get("items", [])),
        next_cursor=found.get("next_cursor"),
        not_answering=[
            f"{f['account_id']}: {f['message']}" for f in found.get("incomplete") or []
        ],
    )


def _changes(found: dict[str, Any]) -> Changes:
    return Changes(
        changes=[
            {key: str(change[key]) for key in ("type", "id", "account_id", "at")}
            for change in found.get("changes", [])
        ],
        state=str(found["state"]),
        more=bool(found.get("more")),
    )


def _outcome(found: dict[str, Any]) -> Outcome:
    done, failed = [], []
    for item in found.get("results", []):
        if item.get("ok"):
            done.append(str(item["id"]))
        else:
            error = item.get("error") or {}
            failed.append(
                {"id": str(item["id"]), "error": error.get("message", "failed")}
            )
    return Outcome(done, failed)
