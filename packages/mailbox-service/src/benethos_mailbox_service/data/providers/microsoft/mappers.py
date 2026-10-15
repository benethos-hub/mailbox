"""Microsoft Graph's mail JSON to this project's models, and a search to
Graph's query parameters. Pure functions.

Graph names flags differently: ``isRead`` is the inverse of ``unread``, a
star is ``flag.flagStatus == "flagged"``, keywords are ``categories``, and
a draft carries ``isDraft``. Keywords with ``$`` are this project's system
keywords. Graph has no place for them: setting or taking one off answers
``501``, and ``$draft`` is read from ``isDraft``.
"""

from __future__ import annotations

from datetime import UTC, datetime
from typing import Any

from ....errors import BadRequestError, NotSupportedError
from ...mail import convert, fields, parse
from ...models import (
    Address,
    Folder,
    FolderRole,
    Mark,
    Message,
    MessageFilter,
    MessageSummary,
    MessageUpdate,
)
from .. import rules
from . import marks
from .shapes import MailFolder, Recipient, Recipients
from .shapes import Message as GraphMessage

DRAFT_KEYWORD = "$draft"
# The folder with the role ``all``, which Exchange does not have: every
# folder but the trash and junk, as Gmail's All Mail (UNIFORM 6.5).
ALL = "all"
OUTSIDE_ALL = frozenset({FolderRole.TRASH, FolderRole.JUNK})

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
    "sentDateTime,receivedDateTime,bodyPreview,isRead,flag,categories,hasAttachments,isDraft,"
    "internetMessageId"
)
# What a message is read with: its fields, and the verb Outlook last
# carried out on it, which says whether it was answered or forwarded.
SUMMARY_PARAMS = {"$select": SUMMARY_FIELDS, "$expand": marks.EXPAND}
FOLDER_FIELDS = (
    "id,displayName,parentFolderId,totalItemCount,unreadItemCount,childFolderCount"
)


def all_mail() -> Folder:
    """The folder ``all``, which only this service shows."""
    return Folder(id=ALL, name="All Mail", role=FolderRole.ALL)


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
    """The categories as Outlook spells them, ``$answered`` or
    ``$forwarded`` by the verb Outlook last carried out, and ``$draft`` for
    a draft."""
    found = [c for c in item.categories if c]
    if (mark := marks.read(item)) is not None:
        found.append(mark.value)
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
        date=item.sent_date_time,
        received=item.received_date_time,
        snippet=item.body_preview or None,
        unread=item.is_read is False,
        starred=item.flag is not None and item.flag.flag_status == "flagged",
        keywords=keywords(item),
        has_attachments=bool(item.has_attachments),
    )


def message(item: GraphMessage, raw: bytes) -> Message:
    """The whole message: what Graph knows of it, and what its MIME says,
    read as for any other provider."""
    found = convert.message_fields(parse.ParsedMessage(raw))
    return Message(**{**summary(item).model_dump(by_alias=False), **found})


def sent_copy(draft: GraphMessage, sent: str | None) -> MessageSummary:
    """The copy in Sent Items of a draft just sent, which keeps the
    draft's id, in the folder ``sent``."""
    copy = draft.model_copy(update={"parent_folder_id": sent, "is_draft": False})
    return summary(copy)


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


def touches_marks(changes: MessageUpdate) -> bool:
    """Whether ``changes`` name a keyword with ``$``, which Outlook keeps
    no place for."""
    named = [
        *(changes.keywords or []),
        *(changes.add_keywords or []),
        *(changes.remove_keywords or []),
    ]
    return any(k.startswith("$") for k in named)


def marks_changed(item: GraphMessage, changes: MessageUpdate) -> list[str]:
    """The keywords with ``$`` that ``changes`` would set or take off
    ``item``. Outlook keeps ``$answered`` and ``$forwarded`` as a verb, and
    ``$draft``, which it sets itself."""
    present = {k for k in keywords(item) if k.startswith("$")}
    if changes.keywords is not None:
        wanted = {k.lower() for k in changes.keywords if k.startswith("$")}
    else:
        added = {k.lower() for k in changes.add_keywords or [] if k.startswith("$")}
        removed = {
            k.lower() for k in changes.remove_keywords or [] if k.startswith("$")
        }
        wanted = (present | added) - removed
    return sorted(wanted ^ present)


def verb_after(item: GraphMessage, changes: MessageUpdate) -> dict[str, Any]:
    """The PATCH body that sets the verb for the marks ``changes`` set or
    take off, ``{}`` where they stay. Every other mark with ``$`` is
    refused: Outlook keeps no place for it."""
    changed = marks_changed(item, changes)
    refused = [k for k in changed if k not in marks.WRITTEN]
    if refused:
        raise NotSupportedError(
            "outlook keeps no keywords with $ but $answered and $forwarded: "
            + ", ".join(refused)
        )
    if not changed:
        return {}
    present = {k for k in keywords(item) if k.startswith("$")}
    added = [Mark(k) for k in changed if k not in present]
    if len(added) > 1:
        raise BadRequestError(
            "outlook keeps one of $answered and $forwarded: the last verb"
        )
    return marks.patch(added[0] if added else None)


def categories_after(item: GraphMessage, changes: MessageUpdate) -> list[str]:
    """The categories of ``item`` once ``changes`` add and take off
    keywords, those it keeps spelled as Outlook has them."""
    removed = {k.lower() for k in changes.remove_keywords or []}
    kept = [c for c in item.categories if c and c.lower() not in removed]
    present = {c.lower() for c in kept}
    added = [k for k in changes.add_keywords or [] if k.lower() not in present]
    return kept + added


def _graph_day(moment: datetime) -> str:
    """A moment in UTC as Graph's ``$filter`` takes it."""
    return moment.astimezone(UTC).strftime("%Y-%m-%dT%H:%M:%SZ")


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
        filters.append(
            f"receivedDateTime ge {_graph_day(rules.day_start(search.after))}"
        )
    if search.before:
        filters.append(
            f"receivedDateTime lt {_graph_day(rules.day_start(search.before))}"
        )
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
