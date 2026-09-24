"""IMAP data to the neutral model. Pure functions, testable offline.

Works on the objects ``client`` hands out without importing the library:
messages are read by attribute (``uid``, ``flags``, ``from_values``, ...).
"""

from __future__ import annotations

import base64
import binascii
import json
from datetime import UTC, datetime
from typing import Any

from ....errors import NotFoundError
from ...models import (
    Address,
    Attachment,
    Folder,
    FolderRole,
    Message,
    MessageSummary,
)
from .client import RawFolder

INBOX = "INBOX"

# RFC 6154 special-use flags.
SPECIAL_USE: dict[str, FolderRole] = {
    "\\sent": FolderRole.SENT,
    "\\drafts": FolderRole.DRAFTS,
    "\\trash": FolderRole.TRASH,
    "\\junk": FolderRole.JUNK,
    "\\archive": FolderRole.ARCHIVE,
    "\\all": FolderRole.ALL,
}

_NOT_SELECTABLE = {"\\noselect", "\\nonexistent"}

# Special folders of servers that announce no SPECIAL-USE, by the name the
# mailbox language gives them. Compared case-insensitively with the last
# segment of the folder name. Only used for a role no flag has claimed.
LOCALISED_NAMES: dict[FolderRole, tuple[str, ...]] = {
    FolderRole.SENT: (
        "sent",
        "sent items",
        "sent messages",
        "sent mail",
        "gesendet",
        "gesendete elemente",
        "gesendete objekte",
        "gesendete nachrichten",
    ),
    FolderRole.DRAFTS: ("drafts", "draft", "entwürfe", "entwurf"),
    FolderRole.TRASH: (
        "trash",
        "deleted items",
        "deleted messages",
        "bin",
        "papierkorb",
        "gelöschte elemente",
        "gelöschte objekte",
    ),
    FolderRole.JUNK: (
        "junk",
        "spam",
        "junk e-mail",
        "junk-e-mail",
        "spamverdacht",
        "unerwünscht",
    ),
    FolderRole.ARCHIVE: ("archive", "archiv"),
}


# --- opaque ids ---------------------------------------------------------------


def _encode(prefix: str, *parts: object) -> str:
    raw = json.dumps(parts, separators=(",", ":"), ensure_ascii=False).encode()
    return prefix + base64.urlsafe_b64encode(raw).decode().rstrip("=")


def _decode(prefix: str, value: str, what: str) -> list[Any]:
    if not value.startswith(prefix):
        raise NotFoundError(f"{what} {value} not found")
    text = value[len(prefix) :]
    try:
        parts = json.loads(base64.urlsafe_b64decode(text + "=" * (-len(text) % 4)))
    except (binascii.Error, ValueError, UnicodeDecodeError):
        raise NotFoundError(f"{what} {value} not found") from None
    if not isinstance(parts, list):
        raise NotFoundError(f"{what} {value} not found")
    return parts


def folder_id(name: str) -> str:
    return _encode("f_", name)


def folder_name(value: str) -> str:
    parts = _decode("f_", value, "folder")
    if len(parts) != 1 or not isinstance(parts[0], str):
        raise NotFoundError(f"folder {value} not found")
    return parts[0]


def message_id(folder: str, uidvalidity: int, uid: int) -> str:
    return _encode("m_", folder, uidvalidity, uid)


def parse_message_id(value: str) -> tuple[str, int, int]:
    parts = _decode("m_", value, "message")
    if (
        len(parts) != 3
        or not isinstance(parts[0], str)
        or not all(isinstance(p, int) for p in parts[1:])
    ):
        raise NotFoundError(f"message {value} not found")
    return parts[0], parts[1], parts[2]


def cursor(folder: str, uidvalidity: int, before_uid: int) -> str:
    return _encode("c_", folder, uidvalidity, before_uid)


def parse_cursor(value: str) -> tuple[str, int, int]:
    parts = _decode("c_", value, "cursor")
    if len(parts) != 3:
        raise NotFoundError(f"cursor {value} not found")
    return parts[0], parts[1], parts[2]


# --- folders ------------------------------------------------------------------


def to_folders(raws: list[RawFolder]) -> list[Folder]:
    """Every selectable folder, with roles from flags first, then from the
    localised names for roles no flag claimed."""
    folders = [f for f in (to_folder(raw) for raw in raws) if f is not None]
    claimed = {f.role for f in folders if f.role is not None}
    names = {f.id: f.name.casefold() for f in folders}
    result = []
    for folder in folders:
        if folder.role is None:
            for role, candidates in LOCALISED_NAMES.items():
                if role not in claimed and names[folder.id] in candidates:
                    folder = folder.model_copy(update={"role": role})
                    claimed.add(role)
                    break
        result.append(folder)
    return result


def to_folder(raw: RawFolder) -> Folder | None:
    """A folder, or ``None`` for one that cannot hold messages."""
    flags = {flag.lower() for flag in raw.flags}
    if flags & _NOT_SELECTABLE:
        return None
    parent = None
    if raw.delimiter and raw.delimiter in raw.name:
        parent = folder_id(raw.name.rsplit(raw.delimiter, 1)[0])
    display = raw.name.rsplit(raw.delimiter, 1)[-1] if raw.delimiter else raw.name
    return Folder(
        id=folder_id(raw.name),
        name=display,
        role=role_of(raw.name, flags),
        parent_id=parent,
    )


def role_of(name: str, flags: set[str]) -> FolderRole | None:
    if name.upper() == INBOX:
        return FolderRole.INBOX
    for flag in flags:
        if flag in SPECIAL_USE:
            return SPECIAL_USE[flag]
    return None


# --- messages -----------------------------------------------------------------


def to_summary(msg: Any, folder: str, uidvalidity: int) -> MessageSummary:
    return MessageSummary.model_validate(_summary_fields(msg, folder, uidvalidity))


def to_message(msg: Any, folder: str, uidvalidity: int) -> Message:
    attachments = [
        Attachment(
            id=f"att_{index}",
            filename=part.filename or None,
            content_type=part.content_type or "application/octet-stream",
            size=part.size,
            inline=(part.content_disposition or "").lower() == "inline",
        )
        for index, part in enumerate(msg.attachments)
    ]
    headers = {k.lower(): v for k, v in msg.headers.items()}
    fields = _summary_fields(msg, folder, uidvalidity)
    fields["has_attachments"] = bool(attachments)
    return Message.model_validate(
        {
            **fields,
            "cc": _addresses(msg.cc_values),
            "bcc": _addresses(msg.bcc_values),
            "reply_to": _addresses(msg.reply_to_values),
            "message_id_header": _first(headers.get("message-id")),
            "in_reply_to": _first(headers.get("in-reply-to")),
            "text_body": msg.text or None,
            "html_body": msg.html or None,
            "attachments": attachments,
        }
    )


def attachment_index(attachment_id: str) -> int:
    if not attachment_id.startswith("att_") or not attachment_id[4:].isdigit():
        raise NotFoundError(f"attachment {attachment_id} not found")
    return int(attachment_id[4:])


def _summary_fields(msg: Any, folder: str, uidvalidity: int) -> dict[str, Any]:
    flags = {flag.lower() for flag in msg.flags}
    headers = {k.lower(): v for k, v in msg.headers.items()}
    content_type = (_first(headers.get("content-type")) or "").lower()
    sender = msg.from_values
    return {
        "id": message_id(folder, uidvalidity, int(msg.uid)),
        "folder_ids": [folder_id(folder)],
        "subject": msg.subject or None,
        "from": _address(sender) if sender and sender.email else None,
        "to": _addresses(msg.to_values),
        "date": _date(msg.date),
        "unread": "\\seen" not in flags,
        "starred": "\\flagged" in flags,
        "has_attachments": content_type.startswith("multipart/mixed"),
    }


def _address(value: Any) -> Address:
    return Address(email=unicode_address(value.email), name=value.name or None)


def unicode_address(email: str) -> str:
    """An address with an internationalised domain in Unicode: on the wire it
    travels as punycode (``xn--``), the API shows it as people write it."""
    local, at, domain = email.rpartition("@")
    if not at or "xn--" not in domain.lower():
        return email
    try:
        return f"{local}@{domain.encode('ascii').decode('idna')}"
    except UnicodeError:
        return email


def _addresses(values: Any) -> list[Address]:
    return [_address(v) for v in values or () if v.email]


def _first(value: Any) -> str | None:
    if isinstance(value, tuple | list):
        return str(value[0]).strip() if value else None
    return str(value).strip() if value else None


def _date(value: datetime | None) -> datetime | None:
    # imap-tools answers an unparsable Date header with 1900-01-01.
    if value is None or value.year <= 1900:
        return None
    # A Date header without a zone is taken as UTC, so every date carries one.
    return value if value.tzinfo is not None else value.replace(tzinfo=UTC)
