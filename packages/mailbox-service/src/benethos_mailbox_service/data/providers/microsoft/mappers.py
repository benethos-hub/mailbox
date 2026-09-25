"""Microsoft Graph's mail JSON to this project's models, and a search to
Graph's query parameters. Pure functions.

Graph names flags differently: ``isRead`` is the inverse of ``unread``, a
star is ``flag.flagStatus == "flagged"``, keywords are ``categories``, and
a draft carries ``isDraft``. Keywords with ``$`` are this project's system
keywords. Graph has no place for them, so they are not stored.
"""

from __future__ import annotations

from datetime import date, datetime, time
from typing import Any

from ...mail.fields import OCTET_STREAM, unicode_address
from ...models import (
    Address,
    Attachment,
    AttachmentContent,
    Folder,
    FolderRole,
    Message,
    MessageFilter,
    MessageSummary,
)

DRAFT_KEYWORD = "$draft"

# Graph's well-known folder names, and the role each one has here.
WELL_KNOWN: dict[str, FolderRole] = {
    "inbox": FolderRole.INBOX,
    "sentitems": FolderRole.SENT,
    "drafts": FolderRole.DRAFTS,
    "deleteditems": FolderRole.TRASH,
    "junkemail": FolderRole.JUNK,
    "archive": FolderRole.ARCHIVE,
}

SUMMARY_FIELDS = (
    "id,conversationId,parentFolderId,subject,from,toRecipients,"
    "receivedDateTime,bodyPreview,isRead,flag,categories,hasAttachments,isDraft,"
    "internetMessageId"
)
MESSAGE_FIELDS = f"{SUMMARY_FIELDS},ccRecipients,bccRecipients,replyTo,body"
FOLDER_FIELDS = (
    "id,displayName,parentFolderId,totalItemCount,unreadItemCount,childFolderCount"
)


def folder(item: dict[str, Any], roles: dict[str, FolderRole]) -> Folder:
    folder_id = str(item["id"])
    return Folder(
        id=folder_id,
        name=str(item.get("displayName") or ""),
        role=roles.get(folder_id),
        parent_id=item.get("parentFolderId"),
        total=item.get("totalItemCount"),
        unread=item.get("unreadItemCount"),
    )


def _address(value: Any) -> Address | None:
    email = (value or {}).get("emailAddress") or {}
    address = email.get("address")
    if not address:
        return None
    return Address(email=unicode_address(str(address)), name=email.get("name") or None)


def _addresses(values: Any) -> list[Address]:
    found = (_address(v) for v in values or [])
    return [a for a in found if a is not None]


def _when(value: Any) -> datetime | None:
    if not value:
        return None
    return datetime.fromisoformat(str(value).replace("Z", "+00:00"))


def keywords(item: dict[str, Any]) -> list[str]:
    """Lower case, as the other adapters answer keywords."""
    found = [str(c).lower() for c in item.get("categories") or []]
    if item.get("isDraft"):
        found.append(DRAFT_KEYWORD)
    return found


def summary(item: dict[str, Any]) -> MessageSummary:
    return MessageSummary(
        id=str(item["id"]),
        thread_id=item.get("conversationId"),
        folder_ids=[item["parentFolderId"]] if item.get("parentFolderId") else [],
        subject=item.get("subject"),
        sender=_address(item.get("from")),
        to=_addresses(item.get("toRecipients")),
        date=_when(item.get("receivedDateTime")),
        snippet=item.get("bodyPreview") or None,
        unread=not item.get("isRead", True),
        starred=(item.get("flag") or {}).get("flagStatus") == "flagged",
        keywords=keywords(item),
        has_attachments=bool(item.get("hasAttachments")),
    )


def message(item: dict[str, Any], attachments: list[dict[str, Any]]) -> Message:
    body = item.get("body") or {}
    content = body.get("content") or None
    is_html = str(body.get("contentType", "")).lower() == "html"
    return Message(
        **summary(item).model_dump(by_alias=False),
        cc=_addresses(item.get("ccRecipients")),
        bcc=_addresses(item.get("bccRecipients")),
        reply_to=_addresses(item.get("replyTo")),
        message_id_header=item.get("internetMessageId"),
        text_body=None if is_html else content,
        html_body=content if is_html else None,
        attachments=[attachment(a) for a in attachments],
    )


def attachment(item: dict[str, Any]) -> Attachment:
    return Attachment(
        id=str(item["id"]),
        filename=item.get("name") or None,
        content_type=item.get("contentType") or OCTET_STREAM,
        size=int(item.get("size") or 0),
        inline=bool(item.get("isInline")),
    )


def attachment_content(item: dict[str, Any], data: bytes) -> AttachmentContent:
    return AttachmentContent(
        filename=item.get("name") or None,
        content_type=item.get("contentType") or OCTET_STREAM,
        data=data,
    )


def changes(
    unread: bool | None, starred: bool | None, keywords: list[str] | None
) -> dict[str, Any]:
    """The PATCH body of a message update."""
    body: dict[str, Any] = {}
    if unread is not None:
        body["isRead"] = not unread
    if starred is not None:
        body["flag"] = {"flagStatus": "flagged" if starred else "notFlagged"}
    if keywords is not None:
        body["categories"] = [k for k in keywords if not k.startswith("$")]
    return body


def _day(value: date) -> str:
    return datetime.combine(value, time.min).strftime("%Y-%m-%dT%H:%M:%SZ")


def _quoted(value: str) -> str:
    """A value for Graph's search syntax, quoted. ``query`` turns the
    double quotes into single ones inside the whole ``$search`` string."""
    return '"' + value.replace('"', " ").replace("\\", " ").strip() + '"'


def query(search: MessageFilter | None) -> tuple[dict[str, str], MessageFilter | None]:
    """Graph's query parameters for a search, and what is left to check on
    each result because Graph cannot combine it.

    Without text: ``$filter`` and ``$orderby``, newest first. Graph wants
    the ordered property first in the filter, hence the always-true date.
    With text: ``$search``, which allows no ``$filter`` or ``$orderby``.
    Its results come newest first, under ids the adapter translates. Read
    state and star are then checked here.
    """
    search = search or MessageFilter()
    texts = []
    if search.text:
        texts.append(_quoted(search.text))
    if search.sender:
        texts.append(f"from:{_quoted(search.sender)}")
    if search.to:
        texts.append(f"to:{_quoted(search.to)}")
    if search.subject:
        texts.append(f"subject:{_quoted(search.subject)}")
    if texts:
        if search.has_attachments:
            texts.append("hasAttachments:true")
        if search.after:
            texts.append(f"received>={search.after.isoformat()}")
        if search.before:
            texts.append(f"received<{search.before.isoformat()}")
        left = MessageFilter(unread=search.unread, starred=search.starred)
        rest = left if left.unread is not None or left.starred is not None else None
        return {
            "$search": '"' + " ".join(t.replace('"', "'") for t in texts) + '"'
        }, rest
    filters = ["receivedDateTime ge 1900-01-01T00:00:00Z"]
    if search.after:
        filters.append(f"receivedDateTime ge {_day(search.after)}")
    if search.before:
        filters.append(f"receivedDateTime lt {_day(search.before)}")
    if search.unread is not None:
        filters.append(f"isRead eq {'false' if search.unread else 'true'}")
    if search.starred is not None:
        flag = "eq" if search.starred else "ne"
        filters.append(f"flag/flagStatus {flag} 'flagged'")
    if search.has_attachments is not None:
        filters.append(f"hasAttachments eq {str(search.has_attachments).lower()}")
    return {"$filter": " and ".join(filters), "$orderby": "receivedDateTime desc"}, None


def keeps(item: MessageSummary, rest: MessageFilter | None) -> bool:
    """Whether a search result passes what Graph could not check."""
    if rest is None:
        return True
    if rest.unread is not None and item.unread != rest.unread:
        return False
    return rest.starred is None or item.starred == rest.starred
