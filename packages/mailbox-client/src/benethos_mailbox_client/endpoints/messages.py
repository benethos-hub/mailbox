"""Messages: listed and searched in one account or across every account
the caller may read, the changes since a state, one message and its
source, an attachment, flags, keywords and moves for one or many at
once, deleting. The page of
summaries is read here for the drafts as well."""

from __future__ import annotations

from typing import Any

from ..calls import ATTACHMENT_TIMEOUT, Call, as_is, given, nothing, path
from ..models import Change, Changes, Failed, Outcome, Page


def list_messages(
    account_id: str,
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
    """One account's messages, newest first. ``folder`` is an id or a
    role. ``list_all_messages`` searches every account."""
    return Call(
        "GET",
        path("accounts", account_id, "messages"),
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


def list_all_messages(
    *,
    accounts: list[str] | None = None,
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
    limit: int | None = None,
    cursor: str | None = None,
) -> Call[Page]:
    """The messages of every account the caller may read, or of those in
    ``accounts``, newest first. ``folder`` is a role such as ``inbox``.
    ``after`` and ``before`` are days, YYYY-MM-DD."""
    return Call(
        "GET",
        path("messages"),
        page,
        params=given(
            {
                "accounts": accounts,
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


def list_all_changes(
    *,
    accounts: list[str] | None = None,
    since: str | None = None,
    limit: int | None = None,
) -> Call[Changes]:
    """The changes of every account the caller may read, or of those in
    ``accounts``, after the point ``since``. Without it, only the state
    to start from."""
    return Call(
        "GET",
        path("changes"),
        _changes,
        params=given({"accounts": accounts, "since": since, "limit": limit}),
    )


def list_changes(account_id: str, *, since: str | None, limit: int) -> Call[Changes]:
    """The changes of one account after the point ``since``.
    ``list_all_changes`` follows every account."""
    return Call(
        "GET",
        path("accounts", account_id, "changes"),
        _changes,
        params=given({"since": since, "limit": limit}),
    )


def get_message(account_id: str, message_id: str) -> Call[dict[str, Any]]:
    return Call("GET", path("accounts", account_id, "messages", message_id), dict)


def get_message_raw(account_id: str, message_id: str) -> Call[bytes]:
    """The message as it came, in RFC 5322: headers, body and
    attachments, the bytes as the provider holds them."""
    return Call(
        "GET",
        path("accounts", account_id, "messages", message_id, "raw"),
        bytes,
        timeout=ATTACHMENT_TIMEOUT,
        raw=True,
    )


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


def update_message(
    account_id: str,
    message_id: str,
    *,
    unread: bool | None = None,
    starred: bool | None = None,
    keywords: list[str] | None = None,
    folder_ids: list[str] | None = None,
) -> Call[dict[str, Any]]:
    """Flags, keywords and folders of one message. ``keywords`` replaces
    its list, ``folder_ids`` moves it, by id or by a role such as
    ``archive``. Answers its summary, as the API describes it."""
    return Call(
        "PATCH",
        path("accounts", account_id, "messages", message_id),
        dict,
        json=given(
            {
                "unread": unread,
                "starred": starred,
                "keywords": keywords,
                "folder_ids": folder_ids,
            }
        ),
    )


def batch_messages(
    account_id: str,
    ids: list[str],
    action: str,
    *,
    changes: dict[str, Any] | None = None,
    permanent: bool | None = None,
) -> Call[Outcome]:
    """One action for up to 100 messages: ``update`` with ``changes`` as
    ``update_message`` takes them, or ``delete``, with ``permanent`` for
    good. ``update_messages`` and ``trash_messages`` are the usual ones."""
    return _batch(
        account_id,
        {"ids": ids, "action": action, "changes": changes, "permanent": permanent},
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
            Change(
                type=str(change["type"]),
                id=str(change["id"]),
                account_id=str(change["account_id"]),
                at=str(change["at"]),
            )
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
                Failed(id=str(item["id"]), error=str(error.get("message", "failed")))
            )
    return Outcome(done, failed)
