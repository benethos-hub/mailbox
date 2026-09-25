"""A message's bytes, parsed. The only module that imports ``imap_tools``.

imap-tools is used here for its mail parser only: headers decoded, addresses,
dates, text and HTML bodies with broken charsets handled, attachments. It
speaks no protocol here: the bytes come from IMAP, POP3 or anywhere else.
``ParsedMessage`` answers in this project's types, so replacing the parser,
e.g. with the standard library's ``email``, rewrites this module and
nothing else.
"""

from __future__ import annotations

from dataclasses import dataclass
from datetime import UTC, datetime
from functools import cached_property
from typing import Any

from imap_tools import MailMessage

from ..models import Address
from .fields import OCTET_STREAM, message_id, unicode_address


@dataclass(frozen=True)
class ParsedAttachment:
    filename: str | None
    content_type: str
    size: int
    inline: bool
    payload: bytes


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

    @property
    def message_id(self) -> str | None:
        return message_id(self.header("message-id"))

    @property
    def content_type(self) -> str:
        return (self.header("content-type") or "").lower()

    @property
    def text(self) -> str | None:
        return self._parsed.text or None

    @property
    def html(self) -> str | None:
        return self._parsed.html or None

    @cached_property
    def attachments(self) -> list[ParsedAttachment]:
        return [
            ParsedAttachment(
                filename=part.filename or None,
                content_type=part.content_type or OCTET_STREAM,
                size=part.size,
                inline=(part.content_disposition or "").lower() == "inline",
                payload=part.payload,
            )
            for part in self._parsed.attachments
        ]


def _address(value: Any) -> Address:
    return Address(email=unicode_address(value.email), name=value.name or None)


def _addresses(values: Any) -> list[Address]:
    return [_address(v) for v in values or () if v.email]
