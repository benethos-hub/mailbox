"""JMAP data to the neutral model and back: mailboxes, emails, keywords,
filters, cursors. Pure functions, testable offline. What a whole message
says comes from ``data.mail.convert``, read from its source.

Ids are the server's own. JMAP keeps an email's id when it moves (RFC 8620
1.2), and the keywords of the API are those of JMAP (RFC 8621 4.1.1).
"""

from __future__ import annotations

import hashlib
import json
import re
from datetime import UTC, date, datetime, time
from typing import Any

from ....common import opaque
from ....common.clock import parse_iso
from ...mail import convert, parse
from ...models import (
    Folder,
    FolderRole,
    Message,
    MessageFilter,
    MessageSummary,
    MessageUpdate,
)
from .. import rules

# An id as JMAP allows it (RFC 8620 1.2).
_ID = re.compile(r"^[A-Za-z0-9_-]{1,255}$")

ROLES = {role.value: role for role in FolderRole}

MAILBOX_PROPERTIES = [
    "id",
    "name",
    "parentId",
    "role",
    "totalEmails",
    "unreadEmails",
    "isSubscribed",
]
SUMMARY_PROPERTIES = [
    "id",
    "blobId",
    "threadId",
    "mailboxIds",
    "keywords",
    "receivedAt",
    "sentAt",
    "subject",
    "from",
    "to",
    "preview",
    "hasAttachment",
]

# Keywords with a field or an operation of their own in the API.
SEEN = "$seen"
FLAGGED = "$flagged"
DRAFT = "$draft"
_NOT_KEYWORDS = {SEEN, FLAGGED, "$deleted", "$recent"}


def is_id(value: str | None) -> bool:
    """Whether ``value`` can be a JMAP id. Anything else is not found."""
    return value is not None and bool(_ID.match(value))


# --- mailboxes --------------------------------------------------------------------


def folder(mailbox: dict[str, Any]) -> Folder:
    return Folder(
        id=str(mailbox["id"]),
        name=str(mailbox.get("name") or ""),
        role=ROLES.get(str(mailbox.get("role") or "").lower()),
        parent_id=mailbox.get("parentId") or None,
        total=mailbox.get("totalEmails"),
        unread=mailbox.get("unreadEmails"),
        subscribed=mailbox.get("isSubscribed"),
    )


# --- emails -----------------------------------------------------------------------


def summary(email: dict[str, Any]) -> MessageSummary:
    flags = email.get("keywords") or {}
    sender = _addresses(email.get("from"))
    return MessageSummary.model_validate(
        {
            "id": str(email["id"]),
            "thread_id": email.get("threadId"),
            "folder_ids": sorted(email.get("mailboxIds") or {}),
            "subject": email.get("subject"),
            "from": sender[0] if sender else None,
            "to": _addresses(email.get("to")),
            "date": when(email.get("sentAt")) or when(email.get("receivedAt")),
            "snippet": email.get("preview") or None,
            "unread": SEEN not in flags,
            "starred": FLAGGED in flags,
            "keywords": keywords(flags),
            "has_attachments": bool(email.get("hasAttachment")),
        }
    )


def message(email: dict[str, Any], raw: bytes) -> Message:
    """The whole message: what JMAP knows of it, and what its source says."""
    parsed = parse.ParsedMessage(raw)
    fields = {**convert.summary_fields(parsed), **convert.message_fields(parsed)}
    if fields.get("date") is None:
        fields.pop("date", None)  # no Date header: when it arrived stays
    return Message.model_validate(
        {**summary(email).model_dump(by_alias=True), **fields}
    )


def keywords(flags: dict[str, Any]) -> list[str]:
    """The API's keywords of an email's JMAP keywords, sorted."""
    return sorted(
        k.lower() for k, on in flags.items() if on and k.lower() not in _NOT_KEYWORDS
    )


def keyword_patch(current: dict[str, Any], changes: MessageUpdate) -> dict[str, Any]:
    """The patch of an email's keywords for ``changes`` (RFC 8620 5.3),
    given the keywords it has now."""
    patch: dict[str, Any] = {}
    if changes.unread is not None:
        patch[_path(SEEN)] = None if changes.unread else True
    if changes.starred is not None:
        patch[_path(FLAGGED)] = True if changes.starred else None
    if changes.keywords is not None:
        wanted = {k.lower() for k in changes.keywords}
        present = set(keywords(current))
        for keyword in wanted - present:
            patch[_path(keyword)] = True
        for keyword in present - wanted:
            patch[_path(keyword)] = None
    return patch


def _path(keyword: str) -> str:
    """A keyword in a patch path, escaped as a JSON pointer."""
    return "keywords/" + keyword.replace("~", "~0").replace("/", "~1")


def when(value: Any) -> datetime | None:
    if not isinstance(value, str) or not value:
        return None
    try:
        return parse_iso(value.replace("Z", "+00:00"))
    except ValueError:
        return None


def _addresses(values: Any) -> list[dict[str, Any]]:
    return [
        {"email": str(v["email"]), "name": v.get("name") or None}
        for v in values or []
        if isinstance(v, dict) and v.get("email")
    ]


# --- lists ------------------------------------------------------------------------


def query_filter(folder_id: str | None, search: MessageFilter | None) -> dict[str, Any]:
    """The API's filter as a JMAP FilterOperator: every condition must hold."""
    search = search or MessageFilter()
    conditions: list[dict[str, Any]] = []
    if folder_id is not None:
        conditions.append({"inMailbox": folder_id})
    for field, name in (
        ("text", "text"),
        ("sender", "from"),
        ("to", "to"),
        ("subject", "subject"),
    ):
        value = getattr(search, field)
        if value:
            conditions.append({name: value})
    if search.after is not None:
        conditions.append({"after": _midnight(search.after)})
    if search.before is not None:
        conditions.append({"before": _midnight(search.before)})
    if search.unread is not None:
        conditions.append({"notKeyword" if search.unread else "hasKeyword": SEEN})
    if search.starred is not None:
        conditions.append({"hasKeyword" if search.starred else "notKeyword": FLAGGED})
    if search.has_attachments is not None:
        conditions.append({"hasAttachment": search.has_attachments})
    return {"operator": "AND", "conditions": conditions}


def _midnight(day: date) -> str:
    return datetime.combine(day, time(), UTC).strftime("%Y-%m-%dT%H:%M:%SZ")


# Newest first, as every list of the API.
SORT = [{"property": "receivedAt", "isAscending": False}]


def scope(folder_id: str | None, search: MessageFilter | None) -> str:
    """What a cursor belongs to: the folder and the search."""
    what = json.dumps(
        [folder_id, (search or MessageFilter()).model_dump(mode="json")],
        sort_keys=True,
    )
    return hashlib.sha256(what.encode()).hexdigest()[:16]


def cursor(scope_of: str, last_id: str, position: int) -> str:
    """Where the next page starts: after the email ``last_id``, which was at
    ``position``, in case it is gone by then."""
    return opaque.encode("c_", [scope_of, last_id, position])


def parse_cursor(value: str, scope_of: str) -> tuple[str, int]:
    parts = opaque.fields("c_", value, str, str, int)
    if parts is None or parts[0] != scope_of or not is_id(parts[1]):
        raise rules.invalid_cursor()
    return parts[1], parts[2]
