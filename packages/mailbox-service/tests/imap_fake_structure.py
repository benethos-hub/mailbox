"""BODYSTRUCTURE of the fake IMAP server (RFC 3501 7.4.2), built from a
message's source in the shape IMAPClient answers it: a multipart as a
list of its parts followed by its subtype, a part as its fields, the
names and values in bytes."""

from __future__ import annotations

from email import message_from_bytes
from email.message import Message
from email.policy import compat32
from typing import Any


def structure(raw: bytes) -> tuple[Any, ...]:
    return _part(message_from_bytes(raw, policy=compat32))


def _part(part: Message) -> tuple[Any, ...]:
    if part.get_content_type() == "message/rfc822":
        [inner] = part.get_payload()
        cid = part.get("Content-ID")
        how = _disposition(part)
        return (
            b"MESSAGE",
            b"RFC822",
            None,
            cid.encode() if cid else None,
            None,
            b"7BIT",
            0,
            None,
            _part(inner),
            0,
            None,
            how,
        )
    if part.is_multipart():
        inner = [_part(p) for p in part.get_payload()]
        return (inner, part.get_content_subtype().upper().encode())
    params = _flat(part.get_params(header="content-type")[1:] or [])
    payload = part.get_payload(decode=False)
    size = len(payload) if isinstance(payload, str) else 0
    cid = part.get("Content-ID")
    basic = (
        part.get_content_maintype().upper().encode(),
        part.get_content_subtype().upper().encode(),
        params or None,
        cid.encode() if cid else None,
        None,
        (part.get("Content-Transfer-Encoding") or "7BIT").upper().encode(),
        size,
    )
    how = _disposition(part)
    lines = (payload.count("\n"),) if part.get_content_maintype() == "text" else ()
    return (*basic, *lines, None, how, None, None)


def _disposition(part: Message) -> tuple[Any, ...] | None:
    if not part.get("Content-Disposition"):
        return None
    found = part.get_params(header="content-disposition") or []
    return (found[0][0].upper().encode(), _flat(found[1:]) or None)


def _flat(pairs: list[tuple[str, str]]) -> tuple[bytes, ...]:
    return tuple(
        item.encode() for name, value in pairs for item in (name.upper(), str(value))
    )
