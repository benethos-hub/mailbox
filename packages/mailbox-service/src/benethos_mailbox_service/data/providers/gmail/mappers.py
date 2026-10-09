"""Gmail's labels and messages in the terms of the API.

Labels are folders, and a message can carry several (``LABELS``). The
system labels with a role are folders, and so are the labels a person
made. ``STARRED`` and ``UNREAD`` are flags. ``IMPORTANT``, the
categories and the chats are left out. "All Mail" has no label: it is
every message outside the trash and the spam, here the folder
``ALL_MAIL`` with the role ``all``. Archiving takes ``INBOX`` off.
"""

from __future__ import annotations

import html
from datetime import UTC, date, datetime, time
from typing import Any

from ....common import opaque
from ....common.canonical import canonical
from ....common.secret import digest
from ...mail import convert, parse
from ...models import Folder, FolderRole, Message, MessageFilter, MessageSummary
from .. import rules
from .shapes import GmailMessage, Label

INBOX = "INBOX"
SENT = "SENT"
DRAFT = "DRAFT"
TRASH = "TRASH"
SPAM = "SPAM"
UNREAD = "UNREAD"
STARRED = "STARRED"
# "All Mail": no label of Gmail's, so an id that is none either.
ALL_MAIL = "ALL_MAIL"

# The system labels that are folders, with their role and name.
SYSTEM = {
    INBOX: (FolderRole.INBOX, "Inbox"),
    SENT: (FolderRole.SENT, "Sent"),
    DRAFT: (FolderRole.DRAFTS, "Drafts"),
    TRASH: (FolderRole.TRASH, "Trash"),
    SPAM: (FolderRole.JUNK, "Spam"),
}
ALL_MAIL_NAME = "All Mail"
# Labels Gmail sets itself and a message cannot be moved into.
NOT_TARGETS = frozenset({SENT, DRAFT})
# Outside "All Mail".
OUTSIDE_ALL = frozenset({TRASH, SPAM})

# The headers a summary is made of.
SUMMARY_HEADERS = ("From", "To", "Subject", "Date", "Content-Type", "Message-ID")


def is_folder(label: Label) -> bool:
    return label.id in SYSTEM or label.type == "user"


def folders(labels: list[Label]) -> list[Folder]:
    """The labels that are folders, and "All Mail". A label named
    ``a/b`` sits in the one named ``a`` where there is one."""
    by_name = {label.name: label.id for label in labels if label.type == "user"}
    found = [
        Folder(id=ALL_MAIL, name=ALL_MAIL_NAME, role=FolderRole.ALL),
    ]
    for label in labels:
        if label.id in SYSTEM:
            role, name = SYSTEM[label.id]
            found.append(_counted(Folder(id=label.id, name=name, role=role), label))
        elif label.type == "user" and label.name:
            parent, _, own = label.name.rpartition("/")
            folder = Folder(id=label.id, name=own or label.name)
            folder.parent_id = by_name.get(parent) if parent else None
            found.append(_counted(folder, label))
    return found


def _counted(folder: Folder, label: Label) -> Folder:
    folder.total = label.messages_total
    folder.unread = label.messages_unread
    return folder


def label_name(name: str, parent: Label | None) -> str:
    """A label's full name: Gmail nests labels by their names."""
    return f"{parent.name}/{name}" if parent is not None and parent.name else name


def folder_ids(label_ids: list[str], known: set[str]) -> list[str]:
    """The folders a message with these labels is in. One in the trash or
    the spam keeps its other labels, but is in those alone."""
    found = [i for i in label_ids if i in known]
    outside = [i for i in found if i in OUTSIDE_ALL]
    return outside or [*found, ALL_MAIL]


def in_folder(folder_id: str, label_ids: set[str]) -> bool:
    """Whether a message with these labels is in the folder."""
    return folder_id in folder_ids(sorted(label_ids), label_ids | {folder_id})


def summary(message: GmailMessage, known: set[str]) -> MessageSummary:
    """A message in the format ``metadata``."""
    headers = message.payload.headers if message.payload else []
    parsed = parse.from_headers((h.name, h.value) for h in headers)
    fields = convert.summary_fields(parsed)
    if fields.get("date") is None:
        fields["date"] = received(message)
    return MessageSummary.model_validate(
        {
            "id": message.id,
            "thread_id": message.thread_id,
            **_labels(message, known),
            "snippet": html.unescape(message.snippet) if message.snippet else None,
            **fields,
        }
    )


def message(meta: GmailMessage, raw: bytes, known: set[str]) -> Message:
    """The whole message: what Gmail knows of it, and what its source says."""
    parsed = parse.ParsedMessage(raw)
    fields = {**convert.summary_fields(parsed), **convert.message_fields(parsed)}
    if fields.get("date") is None:
        fields["date"] = received(meta)
    return Message.model_validate(
        {
            "id": meta.id,
            "thread_id": meta.thread_id,
            **_labels(meta, known),
            "snippet": html.unescape(meta.snippet) if meta.snippet else None,
            **fields,
        }
    )


def _labels(message: GmailMessage, known: set[str]) -> dict[str, Any]:
    labels = message.label_ids
    return {
        "folder_ids": folder_ids(labels, known),
        "unread": UNREAD in labels,
        "starred": STARRED in labels,
        "keywords": [],
    }


def received(message: GmailMessage) -> datetime | None:
    """When Gmail received the message."""
    value = message.internal_date
    if not value or not value.isdigit():
        return None
    return datetime.fromtimestamp(int(value) / 1000, UTC)


# --- search --------------------------------------------------------------------------


def query(search: MessageFilter | None) -> str | None:
    """Gmail's search syntax for a filter. Dates count in UTC: Gmail takes
    seconds since 1970 for ``after`` and ``before``."""
    if search is None:
        return None
    terms: list[str] = []
    if search.text:
        terms.append(_quoted(search.text))
    for operator, value in (
        ("from", search.sender),
        ("to", search.to),
        ("subject", search.subject),
    ):
        if value:
            terms.append(f"{operator}:{_quoted(value)}")
    if search.after is not None:
        # after: counts from the second after.
        terms.append(f"after:{_seconds(search.after) - 1}")
    if search.before is not None:
        terms.append(f"before:{_seconds(search.before)}")
    for flag, operator in (
        (search.unread, "is:unread"),
        (search.starred, "is:starred"),
        (search.has_attachments, "has:attachment"),
    ):
        if flag is not None:
            terms.append(operator if flag else f"-{operator}")
    return " ".join(terms) or None


def _quoted(text: str) -> str:
    """A phrase, the quotes in it left out."""
    return '"' + " ".join(text.replace('"', " ").split()) + '"'


def _seconds(day: date) -> int:
    return int(datetime.combine(day, time(), UTC).timestamp())


# --- cursors -------------------------------------------------------------------------


def scope(folder_id: str | None, search: MessageFilter | None) -> str:
    """What a cursor belongs to: the folder and the search, shortened.
    Two that collide cost a page of the other search, never another
    account's mail."""
    what = canonical([folder_id, (search or MessageFilter()).model_dump(mode="json")])
    return digest(what)[:16]


def cursor(scope_of: str, page_token: str) -> str:
    return opaque.encode("g_", [scope_of, page_token])


def page_token(value: str, scope_of: str) -> str:
    parts = opaque.fields("g_", value, str, str)
    if parts is None or parts[0] != scope_of or not parts[1]:
        raise rules.invalid_cursor()
    return str(parts[1])
