"""Each endpoint of the API the client knows, described once: the
request it makes and how its answer becomes a record of ``models``.

A function here sends nothing. It answers a ``Call``, which ``client``
and ``sync`` send. Nothing above this module spells out a path, a query
name or a field of the API.
"""

from __future__ import annotations

from typing import Any

from .models import (
    Changes,
    Folder,
    Me,
    MeAccount,
    Outcome,
    Page,
    Recipient,
    Sending,
    Sent,
)
from .wire import ATTACHMENT_TIMEOUT, Call, given, path


def request(
    method: str,
    where: str,
    *,
    params: dict[str, Any] | None = None,
    json: dict[str, Any] | None = None,
    headers: dict[str, str] | None = None,
) -> Call[Any]:
    """Any request, answered with its JSON as it comes, None for no
    content. Parameters and fields that are None are left out."""
    return Call(
        method,
        where,
        _as_is,
        params=given(params),
        json=given(json) if json is not None else None,
        headers=dict(headers or {}),
    )


# --- the caller and the accounts ------------------------------------------------------


def me() -> Call[Me]:
    return Call("GET", path("me"), _me)


# --- folders --------------------------------------------------------------------------


def list_folders(account_id: str) -> Call[list[Folder]]:
    return Call(
        "GET",
        path("accounts", account_id, "folders"),
        lambda found: [_folder(item) for item in found],
    )


def create_folder(account_id: str, name: str, parent_id: str | None) -> Call[Folder]:
    """A new folder. ``parent_id`` may be a role such as ``archive``."""
    return Call(
        "POST",
        path("accounts", account_id, "folders"),
        _folder,
        json=given({"name": name, "parent_id": parent_id}),
    )


# --- messages -------------------------------------------------------------------------


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
        _page,
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
        _as_is,
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


def trash_messages(account_id: str, message_ids: list[str]) -> Call[Outcome]:
    return _batch(account_id, {"ids": message_ids, "action": "delete"})


def _batch(account_id: str, body: dict[str, Any]) -> Call[Outcome]:
    return Call(
        "POST",
        path("accounts", account_id, "messages", "batch"),
        _outcome,
        json=given(body),
    )


# --- drafts and sending ---------------------------------------------------------------


def list_drafts(account_id: str, limit: int, cursor: str | None) -> Call[Page]:
    return Call(
        "GET",
        path("accounts", account_id, "drafts"),
        _page,
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
    return Call("DELETE", path("accounts", account_id, "drafts", draft_id), _nothing)


def send_message(
    account_id: str, message: dict[str, Any], idempotency_key: str
) -> Call[Sent]:
    return Call(
        "POST",
        path("accounts", account_id, "send"),
        _sent,
        json=given(message),
        headers={"Idempotency-Key": idempotency_key},
    )


def send_draft(account_id: str, draft_id: str, idempotency_key: str) -> Call[Sent]:
    return Call(
        "POST",
        path("accounts", account_id, "drafts", draft_id, "send"),
        _sent,
        headers={"Idempotency-Key": idempotency_key},
    )


def message_body(
    *,
    to: list[Recipient],
    cc: list[Recipient],
    bcc: list[Recipient],
    subject: str,
    text: str,
    html: str | None,
    reference: tuple[str, str] | None,
) -> dict[str, Any]:
    """The body of a draft or a message to send, as the API takes it.
    ``reference``: the id of the message answered or forwarded, and the
    action (reply, reply_all, forward)."""
    body: dict[str, Any] = {
        "to": [_recipient(r) for r in to],
        "cc": [_recipient(r) for r in cc],
        "bcc": [_recipient(r) for r in bcc],
        "subject": subject,
        "text": text,
    }
    if html is not None:
        body["html"] = html
    if reference is not None:
        body["reference"] = {"message_id": reference[0], "action": reference[1]}
    return body


# --- the readings ---------------------------------------------------------------------


def _scoped(account_id: str | None, what: str) -> str:
    """``what`` of one account, or with ``account_id`` None, of every
    account the caller may use."""
    return path("accounts", account_id, what) if account_id else path(what)


def _as_is(found: Any) -> Any:
    return found


def _nothing(found: Any) -> None:
    return None


def _recipient(recipient: Recipient) -> dict[str, str]:
    email, name = recipient
    return {"email": email, "name": name} if name else {"email": email}


def _me(found: dict[str, Any]) -> Me:
    return Me(
        accounts=[
            MeAccount(
                id=str(a["id"]),
                email=str(a["email"]),
                display_name=a.get("display_name"),
                operations=frozenset(a.get("operations", [])),
                warnings=frozenset(a.get("warnings", [])),
                sending=tuple(_sending(s) for s in a.get("sending", [])),
                capabilities=(
                    frozenset(a["capabilities"]) if "capabilities" in a else None
                ),
            )
            for a in found.get("accounts", [])
        ],
        operations=frozenset(found.get("operations", [])),
    )


def _sending(item: dict[str, Any]) -> Sending:
    recipients = item.get("recipients")
    return Sending(
        recipients=tuple(recipients) if recipients is not None else None,
        max_per_day=item.get("max_sends_per_day"),
        left=item.get("sends_left"),
    )


def _folder(item: dict[str, Any]) -> Folder:
    return Folder(
        id=str(item["id"]),
        name=str(item["name"]),
        role=item.get("role"),
        unread=item.get("unread"),
        total=item.get("total"),
    )


def _page(found: dict[str, Any]) -> Page:
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


def _sent(found: dict[str, Any]) -> Sent:
    return Sent(
        message_id_header=found.get("message_id_header"),
        refused=list(found.get("refused") or []),
    )
