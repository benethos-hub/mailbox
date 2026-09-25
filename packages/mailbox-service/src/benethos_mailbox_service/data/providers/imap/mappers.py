"""IMAP data to the neutral model: ids, folders and flags. Pure functions,
testable offline. What the message itself says comes from ``data.mail.convert``.

Works on the objects ``client`` hands out without importing the library:
messages are read by attribute (``uid``, ``flags``, ``from_values``, ...).
"""

from __future__ import annotations

from typing import Any

from ....common import opaque
from ....errors import MessageNotFoundError, NotFoundError, NotSupportedError
from ...mail import convert
from ...models import (
    Folder,
    FolderRole,
    Message,
    MessageSummary,
    MessageUpdate,
)
from .. import rules
from ..protocols.imap import FetchedMessage, RawFolder

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
    return opaque.encode(prefix, parts)


def _decode(prefix: str, value: str, what: str) -> list[Any]:
    try:
        parts = opaque.decode(prefix, value)
    except ValueError:
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
    try:
        parts = _decode("m_", value, "message")
    except NotFoundError:
        raise MessageNotFoundError(f"message {value} not found") from None
    if (
        len(parts) != 3
        or not isinstance(parts[0], str)
        or not all(isinstance(p, int) for p in parts[1:])
    ):
        raise MessageNotFoundError(f"message {value} not found")
    return parts[0], parts[1], parts[2]


def cursor(folder: str, uidvalidity: int, before_uid: int) -> str:
    return _encode("c_", folder, uidvalidity, before_uid)


def parse_cursor(value: str) -> tuple[str, int, int]:
    try:
        parts = opaque.decode("c_", value)
    except ValueError:
        raise rules.invalid_cursor() from None
    if (
        not isinstance(parts, list)
        or len(parts) != 3
        or not isinstance(parts[0], str)
        or not all(isinstance(p, int) for p in parts[1:])
    ):
        raise rules.invalid_cursor()
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
        subscribed=raw.subscribed,
    )


def role_of(name: str, flags: set[str]) -> FolderRole | None:
    if name.upper() == INBOX:
        return FolderRole.INBOX
    for flag in flags:
        if flag in SPECIAL_USE:
            return SPECIAL_USE[flag]
    return None


# --- messages -----------------------------------------------------------------


def to_summary(msg: FetchedMessage, folder: str, uidvalidity: int) -> MessageSummary:
    return MessageSummary.model_validate(
        {**convert.summary_fields(msg), **_imap_fields(msg, folder, uidvalidity)}
    )


def to_message(msg: FetchedMessage, folder: str, uidvalidity: int) -> Message:
    return Message.model_validate(
        {
            **convert.summary_fields(msg),
            **_imap_fields(msg, folder, uidvalidity),
            **convert.message_fields(msg),
        }
    )


def _imap_fields(msg: FetchedMessage, folder: str, uidvalidity: int) -> dict[str, Any]:
    """What only IMAP knows of a message: its id, folder and flags."""
    flags = {flag.lower() for flag in msg.flags}
    return {
        "id": message_id(folder, uidvalidity, int(msg.uid)),
        "folder_ids": [folder_id(folder)],
        "unread": "\\seen" not in flags,
        "starred": "\\flagged" in flags,
        "keywords": keywords(msg.flags),
    }


# IMAP flags that are keywords in the API, and back (JMAP, RFC 8621).
_SYSTEM_KEYWORDS = {"\\answered": "$answered", "\\draft": "$draft"}
# unread, starred and deletion have their own fields and operations.
_NOT_KEYWORDS = {"\\seen", "\\flagged", "\\deleted", "\\recent"}
# The spelling IMAP servers and clients use for the common keywords.
_IMAP_SPELLING = {
    "$answered": "\\Answered",
    "$draft": "\\Draft",
    "$forwarded": "$Forwarded",
    "$junk": "$Junk",
    "$notjunk": "$NotJunk",
    "$mdnsent": "$MDNSent",
    "$phishing": "$Phishing",
}


def keywords(flags: Any) -> list[str]:
    """The API's keywords of a message's IMAP flags, sorted."""
    found = set()
    for flag in flags:
        lowered = str(flag).lower()
        if lowered in _NOT_KEYWORDS:
            continue
        if lowered in _SYSTEM_KEYWORDS:
            found.add(_SYSTEM_KEYWORDS[lowered])
        elif not lowered.startswith("\\"):
            found.add(lowered)
    return sorted(found)


def imap_flag(keyword: str) -> str:
    """The IMAP flag of an API keyword."""
    lowered = keyword.lower()
    return _IMAP_SPELLING.get(lowered, keyword)


def _kept(flags: list[str], permanent: frozenset[str]) -> bool:
    """Whether the server keeps these flags: it said so with ``\\*``, it
    lists the flag itself, or it sent no PERMANENTFLAGS at all, which
    means every flag is permanent (RFC 3501)."""
    if not permanent or "\\*" in permanent:
        return True
    listed = {f.lower() for f in permanent}
    return all(f.startswith("\\") or f.lower() in listed for f in flags)


def flag_changes(
    current: Any, changes: MessageUpdate, permanent: frozenset[str]
) -> tuple[list[str], list[str]]:
    """The IMAP flags to add and to remove for ``changes``, given the
    message's ``current`` flags and what the server keeps (``permanent``)."""
    add: list[str] = []
    remove: list[str] = []
    if changes.unread is not None:
        (remove if changes.unread else add).append("\\Seen")
    if changes.starred is not None:
        (add if changes.starred else remove).append("\\Flagged")
    if changes.keywords is not None:
        wanted = {k.lower(): k for k in changes.keywords}
        # Each keyword the message has, with the flag as the server spells it.
        present: dict[str, str] = {}
        for flag in current:
            for keyword in keywords([flag]):
                present[keyword] = str(flag)
        new = [imap_flag(wanted[k]) for k in wanted if k not in present]
        if not _kept(new, permanent):
            raise NotSupportedError("the mail server keeps no new keywords")
        add += new
        remove += [flag for k, flag in present.items() if k not in wanted]
    return add, remove
