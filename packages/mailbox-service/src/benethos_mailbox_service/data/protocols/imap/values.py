"""What an IMAP session hands out and takes: folders as the server lists
them, fetched messages, search keys, and the limits."""

from __future__ import annotations

from dataclasses import dataclass
from datetime import date

from benethos_mailbox_common.sizes import MIB

from ...mail import parse

DEFAULT_PORTS = {"tls": 993, "starttls": 143}

# A whole message larger than this is refused, as Graph answers are.
MAX_MESSAGE_BYTES = 40 * MIB
# Headers beyond this are cut off: a list reads many at once.
MAX_HEADER_BYTES = 256 * 1024


@dataclass(frozen=True)
class RawFolder:
    name: str
    delimiter: str | None
    flags: tuple[str, ...]
    subscribed: bool | None = None  # None: not asked


@dataclass(frozen=True)
class FolderState:
    """A folder's state, read without selecting it. The first three change
    whenever a message arrives or leaves, ``highest_modseq`` also when
    flags change (CONDSTORE, RFC 7162). None where not asked or not
    reported."""

    uidvalidity: int
    uidnext: int
    messages: int
    highest_modseq: int | None


@dataclass(frozen=True)
class Namespace:
    """Where top-level folders of the user go (RFC 2342), e.g. ``INBOX.``
    on servers that keep all folders below the inbox, and its delimiter."""

    prefix: str
    delimiter: str | None


@dataclass(frozen=True)
class Selected:
    """A folder selected read-write: its UIDVALIDITY and the flags the
    server keeps (``PERMANENTFLAGS``). ``\\*`` means any keyword."""

    uidvalidity: int
    permanent_flags: frozenset[str]


class FetchedMessage(parse.ParsedMessage):
    """A fetched message: UID and flags as the server reported them, the
    rest parsed from the fetched bytes."""

    def __init__(self, uid: int, flags: tuple[str, ...], raw: bytes) -> None:
        super().__init__(raw)
        self.uid = str(uid)
        self.flags = flags


@dataclass(frozen=True)
class SearchCriteria:
    """IMAP SEARCH keys (RFC 3501 6.4.4). Fields left out do not narrow."""

    text: str | None = None  # TEXT: headers and body
    sender: str | None = None  # FROM
    to: str | None = None  # TO
    subject: str | None = None  # SUBJECT
    since: date | None = None  # SINCE: on or after this day
    before: date | None = None  # BEFORE: before this day
    unread: bool | None = None  # UNSEEN or SEEN
    flagged: bool | None = None  # FLAGGED or UNFLAGGED
    # Content-Type multipart/mixed, as has_attachments reads it in a summary.
    mixed: bool | None = None
    before_uid: int | None = None
