"""Messages: listed and searched in one account or across every account
the caller may read, the changes since a state, one message and its
source, an attachment, flags, keywords and moves for one or many at
once, deleting. A summary, a message and a page of summaries are read
here for the drafts as well."""

from __future__ import annotations

from typing import Any

from ..calls import ATTACHMENT_TIMEOUT, Call, as_is, given, nothing, path
from ..models import (
    Address,
    AttachedFile,
    Change,
    Changes,
    Failed,
    Message,
    MessageSummary,
    Outcome,
    Page,
    Reference,
)
from .readings import maybe_time, time


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


def get_message(account_id: str, message_id: str) -> Call[Message]:
    return Call("GET", path("accounts", account_id, "messages", message_id), message)


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
) -> Call[MessageSummary]:
    """Flags, keywords and folders of one message. ``keywords`` replaces
    its list, ``folder_ids`` moves it, by id or by a role such as
    ``archive``. Answers its summary."""
    return Call(
        "PATCH",
        path("accounts", account_id, "messages", message_id),
        summary,
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
        items=[summary(item) for item in found.get("items", [])],
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
                at=time(change["at"]),
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


def summary(found: dict[str, Any]) -> MessageSummary:
    return MessageSummary(**_summary_fields(found))


def message(found: dict[str, Any]) -> Message:
    reference = found.get("reference")
    return Message(
        **_summary_fields(found),
        cc=_addresses(found.get("cc")),
        bcc=_addresses(found.get("bcc")),
        reply_to=_addresses(found.get("reply_to")),
        message_id_header=found.get("message_id_header"),
        in_reply_to=found.get("in_reply_to"),
        text_body=found.get("text_body"),
        html_body=found.get("html_body"),
        attachments=[_attached(item) for item in found.get("attachments") or []],
        reference=_reference(reference) if reference else None,
    )


def _summary_fields(found: dict[str, Any]) -> dict[str, Any]:
    """What a summary holds, by the names of its record: ``from`` is the
    sender."""
    sender = found.get("from")
    return {
        "id": str(found["id"]),
        "account_id": found.get("account_id"),
        "thread_id": found.get("thread_id"),
        "folder_ids": [str(f) for f in found.get("folder_ids") or []],
        "subject": found.get("subject"),
        "sender": _address(sender) if sender else None,
        "to": _addresses(found.get("to")),
        "date": maybe_time(found.get("date")),
        "snippet": found.get("snippet"),
        "unread": bool(found.get("unread")),
        "starred": bool(found.get("starred")),
        "keywords": [str(k) for k in found.get("keywords") or []],
        "has_attachments": bool(found.get("has_attachments")),
    }


def _address(found: dict[str, Any]) -> Address:
    return Address(email=str(found["email"]), name=found.get("name"))


def _addresses(found: list[dict[str, Any]] | None) -> list[Address]:
    return [_address(item) for item in found or []]


def _attached(found: dict[str, Any]) -> AttachedFile:
    return AttachedFile(
        id=str(found["id"]),
        filename=found.get("filename"),
        content_type=str(found["content_type"]),
        size=int(found["size"]),
        inline=bool(found.get("inline")),
    )


def _reference(found: dict[str, Any]) -> Reference:
    return Reference(
        message_id=str(found["message_id"]),
        action=str(found["action"]),
        forward_as=str(found.get("forward_as", "inline")),
        quote=bool(found.get("quote", True)),
    )
