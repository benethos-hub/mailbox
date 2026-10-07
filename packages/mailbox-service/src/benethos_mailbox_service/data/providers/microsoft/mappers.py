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

from ...mail import fields
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
from .shapes import Attachment as GraphAttachment
from .shapes import MailFolder, Recipient, Recipients
from .shapes import Message as GraphMessage

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


def folder(item: MailFolder, roles: dict[str, FolderRole], root: str) -> Folder:
    """A mail folder. Graph names the mailbox's root folder, which no list
    shows, as the parent of the top ones: for us they have none."""
    parent = item.parent_folder_id
    return Folder(
        id=item.id,
        name=item.display_name or "",
        role=roles.get(item.id),
        parent_id=None if parent == root else parent,
        total=item.total_item_count,
        unread=item.unread_item_count,
    )


def _address(value: Recipient | None) -> Address | None:
    email = value.email_address if value is not None else None
    if email is None or not email.address:
        return None
    return Address(email=fields.unicode_address(email.address), name=email.name or None)


def _addresses(values: Recipients) -> list[Address]:
    found = (_address(v) for v in values)
    return [a for a in found if a is not None]


def keywords(item: GraphMessage) -> list[str]:
    """Lower case, as the other adapters answer keywords."""
    found = [c.lower() for c in item.categories if c]
    if item.is_draft:
        found.append(DRAFT_KEYWORD)
    return found


def summary(item: GraphMessage) -> MessageSummary:
    return MessageSummary(
        id=item.id,
        thread_id=item.conversation_id,
        folder_ids=[item.parent_folder_id] if item.parent_folder_id else [],
        subject=item.subject,
        sender=_address(item.sender),
        to=_addresses(item.to_recipients),
        date=item.received_date_time,
        snippet=item.body_preview or None,
        unread=item.is_read is False,
        starred=item.flag is not None and item.flag.flag_status == "flagged",
        keywords=keywords(item),
        has_attachments=bool(item.has_attachments),
    )


def message(item: GraphMessage, attachments: list[GraphAttachment]) -> Message:
    content = (item.body.content if item.body else None) or None
    kind = (item.body.content_type if item.body else None) or ""
    is_html = kind.lower() == "html"
    return Message(
        **summary(item).model_dump(by_alias=False),
        cc=_addresses(item.cc_recipients),
        bcc=_addresses(item.bcc_recipients),
        reply_to=_addresses(item.reply_to),
        message_id_header=item.internet_message_id,
        text_body=None if is_html else content,
        html_body=content if is_html else None,
        attachments=[attachment(a) for a in attachments],
    )


def attachment(item: GraphAttachment) -> Attachment:
    return Attachment(
        id=item.id,
        filename=item.name or None,
        content_type=item.content_type or fields.OCTET_STREAM,
        size=item.size or 0,
        inline=bool(item.is_inline),
    )


def attachment_content(item: GraphAttachment, data: bytes) -> AttachmentContent:
    return AttachmentContent(
        filename=item.name or None,
        content_type=item.content_type or fields.OCTET_STREAM,
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


def _graph_day(value: date) -> str:
    return datetime.combine(value, time.min).strftime("%Y-%m-%dT%H:%M:%SZ")


def _quoted(value: str) -> str:
    """A value for Graph's search syntax, quoted. ``query`` turns the
    double quotes into single ones inside the whole ``$search`` string, so
    a quote of either kind or a backslash in the value would end the
    phrase and let the rest pass as KQL: each becomes a space."""
    for mark in ('"', "'", "\\"):
        value = value.replace(mark, " ")
    return '"' + value.strip() + '"'


def query(search: MessageFilter | None) -> tuple[dict[str, str], MessageFilter | None]:
    """Graph's query parameters for a search, and what is left to check on
    each result because Graph cannot combine it.

    Without text: ``$filter`` and ``$orderby``, newest first. Graph wants
    the ordered property first in the filter, hence the always-true date.
    With text: ``$search``, which allows no ``$filter`` or ``$orderby``.
    Its results come newest first, under ids the adapter translates. Read
    state, star and the absence of attachments are then checked here.
    """
    search = search or MessageFilter()
    texts = _texts(search)
    if texts:
        return _searched(search, texts)
    return _filtered(search), None


def _texts(search: MessageFilter) -> list[str]:
    """The parts of a search Graph finds with ``$search``."""
    texts = []
    if search.text:
        texts.append(_quoted(search.text))
    if search.sender:
        texts.append(f"from:{_quoted(search.sender)}")
    if search.to:
        texts.append(f"to:{_quoted(search.to)}")
    if search.subject:
        texts.append(f"subject:{_quoted(search.subject)}")
    return texts


def _searched(
    search: MessageFilter, texts: list[str]
) -> tuple[dict[str, str], MessageFilter | None]:
    """``$search`` with the rest of the search that KQL can say, and what
    is left to check on each result."""
    texts = list(texts)
    if search.has_attachments:
        texts.append("hasAttachments:true")
    if search.after:
        texts.append(f"received>={search.after.isoformat()}")
    if search.before:
        texts.append(f"received<{search.before.isoformat()}")
    # KQL finds messages with attachments, not those without.
    without = False if search.has_attachments is False else None
    left = MessageFilter(
        unread=search.unread, starred=search.starred, has_attachments=without
    )
    rest = left if left != MessageFilter() else None
    return {"$search": '"' + " ".join(t.replace('"', "'") for t in texts) + '"'}, rest


def _filtered(search: MessageFilter) -> dict[str, str]:
    """``$filter`` and ``$orderby``, newest first."""
    filters = ["receivedDateTime ge 1900-01-01T00:00:00Z"]
    if search.after:
        filters.append(f"receivedDateTime ge {_graph_day(search.after)}")
    if search.before:
        filters.append(f"receivedDateTime lt {_graph_day(search.before)}")
    if search.unread is not None:
        filters.append(f"isRead eq {'false' if search.unread else 'true'}")
    if search.starred is not None:
        flag = "eq" if search.starred else "ne"
        filters.append(f"flag/flagStatus {flag} 'flagged'")
    if search.has_attachments is not None:
        filters.append(f"hasAttachments eq {str(search.has_attachments).lower()}")
    return {"$filter": " and ".join(filters), "$orderby": "receivedDateTime desc"}


def keeps(item: MessageSummary, rest: MessageFilter | None) -> bool:
    """Whether a search result passes what Graph could not check."""
    return rest is None or rest.flags_match(item)
