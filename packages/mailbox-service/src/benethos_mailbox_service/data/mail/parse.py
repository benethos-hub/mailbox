"""A message's bytes, parsed. The only module that imports ``imap_tools``.

imap-tools is used here for its mail parser only: headers decoded, addresses,
dates, text and HTML bodies with broken charsets handled, attachments. It
speaks no protocol here: the bytes come from IMAP, POP3 or anywhere else.
The bodies are read here part by part, so that a part labelled with a
Western single-byte charset whose bytes are UTF-8 reads as UTF-8.
``ParsedMessage`` answers in this project's types, so replacing the parser,
e.g. with the standard library's ``email``, rewrites this module and
nothing else.
"""

from __future__ import annotations

import codecs
from collections.abc import Iterable
from dataclasses import dataclass
from datetime import UTC, datetime
from email.header import Header
from email.parser import BytesHeaderParser
from email.utils import formataddr, getaddresses, parsedate_to_datetime
from functools import cached_property
from typing import Any

from imap_tools import MailMessage
from imap_tools.utils import decode_value, replace_html_ct_charset

from ..models import Address
from .fields import (
    OCTET_STREAM,
    ThreadHeaders,
    thread_headers,
    unicode_address,
)


@dataclass(frozen=True, slots=True)
class ParsedAttachment:
    filename: str | None
    content_type: str
    size: int
    inline: bool
    payload: bytes
    # Set when the body refers to the part, e.g. an image in the HTML.
    content_id: str | None = None
    # "attachment", "inline" or "" when the part names none.
    disposition: str = ""

    @property
    def attached(self) -> bool:
        """Whether a person sees it as an attachment: not a part the body
        shows in its place, such as an image in the HTML. A file a client
        marked inline, as Apple Mail does with a PDF, is one."""
        return attached(self.content_id, self.disposition)


@dataclass(frozen=True, slots=True)
class PartShape:
    """A part of a message without its content, as IMAP's BODYSTRUCTURE,
    Gmail's parts or JMAP's attachments describe it. ``content_type`` in
    lower case, ``disposition`` "attachment", "inline" or ""."""

    content_type: str
    filename: str | None = None
    disposition: str = ""
    content_id: str | None = None


def attached(content_id: str | None, disposition: str) -> bool:
    """The rule of a real attachment (UNIFORM 6.10): a part the body does
    not name by its Content-ID, or one marked as an attachment."""
    return content_id is None or disposition == "attachment"


def has_attachments(parts: Iterable[PartShape]) -> bool:
    """Whether a person sees one of the parts as an attachment, counted
    as ``ParsedMessage.attachments`` and ``attached`` count them in a
    whole message: a part with a name, a Content-ID or a message inside,
    not the text of the body."""
    for part in parts:
        listed = (
            part.content_id or part.filename or part.content_type == "message/rfc822"
        )
        if not listed or _is_text_body(
            part.content_type, part.filename, part.disposition
        ):
            continue
        if attached(part.content_id, part.disposition):
            return True
    return False


class ParsedMessage:
    """What the message itself says: headers, addresses, date, bodies and
    attachments. What only a protocol knows (ids, folders, flags) an
    adapter adds."""

    def __init__(self, raw: bytes) -> None:
        self._parsed = MailMessage.from_bytes(raw)

    @property
    def subject(self) -> str | None:
        return self._parsed.subject or None

    @property
    def sender(self) -> Address | None:
        found = self._parsed.from_values
        return _address(found) if found and found.email else None

    @property
    def to(self) -> list[Address]:
        return _addresses(self._parsed.to_values)

    @property
    def cc(self) -> list[Address]:
        return _addresses(self._parsed.cc_values)

    @property
    def bcc(self) -> list[Address]:
        return _addresses(self._parsed.bcc_values)

    @property
    def reply_to(self) -> list[Address]:
        return _addresses(self._parsed.reply_to_values)

    @property
    def date(self) -> datetime | None:
        value = self._parsed.date
        # imap-tools answers an unparsable Date header with 1900-01-01.
        if value is None or value.year <= 1900:
            return None
        # A Date header without a zone is taken as UTC, so every date has one.
        return value if value.tzinfo is not None else value.replace(tzinfo=UTC)

    @cached_property
    def headers(self) -> dict[str, str]:
        """Each header's first value, by its lowercased name."""
        found: dict[str, str] = {}
        for name, values in self._parsed.headers.items():
            first = values[0] if isinstance(values, tuple | list) else values
            if first:
                found.setdefault(name.lower(), str(first).strip())
        return found

    def header(self, name: str) -> str | None:
        return self.headers.get(name.lower())

    def all_headers(self, name: str) -> list[str]:
        """Every value of the header ``name``, in their order, as the
        message writes them."""
        return [str(value) for value in self._parsed.obj.get_all(name, [])]

    @property
    def sole_sender(self) -> str | None:
        """The address in ``From`` when it names exactly one, else None."""
        found = [address for _, address in getaddresses(self.all_headers("from"))]
        found = [address for address in found if address]
        return found[0] if len(found) == 1 else None

    @property
    def received(self) -> datetime | None:
        """The time of the topmost ``Received`` header: when the last server
        took the message in. None without one, or where it cannot be read."""
        value = self.header("received")
        if not value or ";" not in value:
            return None
        try:
            when = parsedate_to_datetime(" ".join(value.rsplit(";", 1)[1].split()))
        except (TypeError, ValueError, IndexError):
            return None
        return when if when.tzinfo is not None else when.replace(tzinfo=UTC)

    @property
    def message_id(self) -> str | None:
        return self.thread_headers.message_id

    @property
    def in_reply_to(self) -> str | None:
        """The first id In-Reply-To names: a folded header comes unfolded."""
        return self.thread_headers.in_reply_to

    @property
    def references(self) -> list[str]:
        """The ids References names, oldest first."""
        return list(self.thread_headers.references)

    @property
    def thread_headers(self) -> ThreadHeaders:
        return thread_headers(self.header)

    @property
    def content_type(self) -> str:
        return (self.header("content-type") or "").lower()

    @cached_property
    def text(self) -> str | None:
        return "".join(_bodies(self._parsed, ("text/plain", "text/"))) or None

    @cached_property
    def html(self) -> str | None:
        found = _bodies(self._parsed, ("text/html",))
        return "".join(replace_html_ct_charset(h, "utf-8") for h in found) or None

    @cached_property
    def attachments(self) -> list[ParsedAttachment]:
        return [
            ParsedAttachment(
                filename=part.filename or None,
                content_type=part.content_type or OCTET_STREAM,
                size=part.size,
                inline=(part.content_disposition or "").lower() == "inline",
                payload=part.payload,
                content_id=part.content_id or None,
                disposition=(part.content_disposition or "").lower(),
            )
            for part in self._parsed.attachments
            if not _body(part)
        ]


# Charsets of one byte per character that senders name for text they
# wrote in UTF-8, by the name Python's codecs give them. Every byte is
# valid in them, so a wrong label shows nowhere but in the text.
_MISLABELLED = frozenset({"ascii", "cp1252", "iso8859-1", "iso8859-15"})


def _bodies(parsed: MailMessage, types: tuple[str, ...]) -> list[str]:
    """Each part of the body of one of ``types``, decoded, in the order
    and by the rule of imap-tools: not a container, without a name."""
    found = []
    for part in parsed.obj.walk():
        if part.get_content_maintype() == "multipart" or part.get_filename():
            continue
        if part.get_content_type() in types:
            payload = part.get_payload(decode=True)
            raw = payload if isinstance(payload, bytes) else b""
            found.append(_decoded(raw, part.get_content_charset()))
    return found


def _decoded(payload: bytes, charset: str | None) -> str:
    """The text of a part's bytes in its charset. Bytes beyond ASCII that
    are valid UTF-8 under the label of a Western single-byte charset are
    UTF-8: text really written in such a charset is almost never valid
    UTF-8, as a lone byte for an umlaut is not."""
    if charset and not payload.isascii() and _single_byte(charset):
        try:
            return payload.decode("utf-8")
        except UnicodeDecodeError:
            pass
    return decode_value(payload, charset)


def _single_byte(charset: str) -> bool:
    try:
        return codecs.lookup(charset).name in _MISLABELLED
    except LookupError:
        return False


def _body(part: Any) -> bool:
    """Whether a part imap-tools lists as an attachment is the text of the
    body. It lists every part with a Content-ID, and Exchange gives the
    body one when files are added to a draft one by one. Without a name
    and not marked as an attachment, such a text is the body, as
    ``text`` and ``html`` read it."""
    return _is_text_body(
        part.content_type, part.filename, (part.content_disposition or "").lower()
    )


def _is_text_body(content_type: str, filename: str | None, disposition: str) -> bool:
    return (
        content_type in ("text/plain", "text/html")
        and not filename
        and disposition != "attachment"
    )


# Headers that hold addresses: a name in them is encoded on its own.
_ADDRESS_HEADERS = frozenset({"from", "sender", "to", "cc", "bcc", "reply-to"})


def thread_headers_of(block: bytes) -> ThreadHeaders:
    """The thread headers of a block of header lines alone, such as an IMAP
    server answers for ``BODY[HEADER.FIELDS (...)]``."""
    return thread_headers(BytesHeaderParser().parsebytes(block).get)


def from_headers(headers: Iterable[tuple[str, str]]) -> ParsedMessage:
    """Headers alone, as an API hands them out decoded (Gmail's
    metadata), parsed as a message without a body. Text beyond ASCII is
    encoded again (RFC 2047) so the parser reads it as it would read
    the message itself."""
    lines = [f"{name}: {_encoded(name, value)}" for name, value in headers]
    return ParsedMessage(("\r\n".join(lines) + "\r\n\r\n").encode("utf-8"))


def _encoded(name: str, value: str) -> str:
    value = " ".join(value.split())
    if value.isascii():
        return value
    if name.lower() in _ADDRESS_HEADERS:
        pairs = getaddresses([value])
        return ", ".join(formataddr(pair, charset="utf-8") for pair in pairs)
    return Header(value, "utf-8").encode()


def _address(value: Any) -> Address:
    return Address(email=unicode_address(value.email), name=value.name or None)


def _addresses(values: Any) -> list[Address]:
    return [_address(v) for v in values or () if v.email]
