"""What an IMAP server answers, read: capabilities, flags, body sections,
response codes, UIDs. And its errors as this project's."""

from __future__ import annotations

import imaplib
import re
from collections.abc import Callable
from contextlib import AbstractContextManager, suppress
from datetime import datetime
from email.parser import BytesHeaderParser
from typing import Any

from ....errors import ProviderError, ProviderUnavailableError
from ...mail import fields, parse
from .. import transport
from ..transport import names, text


def translated() -> AbstractContextManager[None]:
    """IMAP's errors as this project's."""
    return transport.translated(
        (
            imaplib.IMAP4.abort,
            lambda exc: ProviderUnavailableError(
                f"the mail server dropped the connection: {exc}"
            ),
        ),
        (
            imaplib.IMAP4.error,
            lambda exc: ProviderError(f"the mail server answered with an error: {exc}"),
        ),
    )


def capabilities(client: Any) -> frozenset[str]:
    return names(client.capabilities())


def flags(data: dict[bytes, Any]) -> tuple[str, ...]:
    return tuple(text(flag) for flag in data.get(b"FLAGS", ()))


def received(data: dict[bytes, Any]) -> datetime | None:
    """INTERNALDATE: when the server received the message. IMAPClient
    answers it in local time without a zone."""
    value = data.get(b"INTERNALDATE")
    if not isinstance(value, datetime):
        return None
    return value if value.tzinfo is not None else value.astimezone()


def structure(data: dict[bytes, Any]) -> tuple[parse.PartShape, ...] | None:
    """The parts BODYSTRUCTURE describes (RFC 3501 7.4.2), without what a
    message attached as a part holds. None where the server sent none."""
    body = data.get(b"BODYSTRUCTURE")
    if not isinstance(body, tuple | list) or not body:
        return None
    found: list[parse.PartShape] = []
    _walk(body, found)
    return tuple(found)


def _walk(body: Any, found: list[parse.PartShape]) -> None:
    if isinstance(body[0], list | tuple):
        # A multipart: its parts first, as IMAPClient lists them.
        for inner in body[0]:
            _walk(inner, found)
        return
    kind = f"{text(body[0])}/{text(body[1])}".lower()
    names = _pairs(body[2])
    # The fields beyond the basic ones: a text has its lines, a message
    # its envelope, its structure and its lines, then MD5, disposition.
    at = (
        8
        + (1 if kind.startswith("text/") else 0)
        + (3 if kind == "message/rfc822" else 0)
    )
    disposition = body[at] if len(body) > at else None
    how, more = ("", {})
    if isinstance(disposition, tuple | list) and disposition:
        how, more = text(disposition[0]).lower(), _pairs(disposition[1])
    named = [
        v for k, v in {**names, **more}.items() if k.startswith(("name", "filename"))
    ]
    found.append(
        parse.PartShape(
            content_type=kind,
            filename=named[0] if named else None,
            disposition=how,
            content_id=text(body[3]) if body[3] else None,
        )
    )


def _pairs(values: Any) -> dict[str, str]:
    """A parameter list of BODYSTRUCTURE, names in lower case."""
    if not isinstance(values, tuple | list):
        return {}
    flat = [text(v) for v in values]
    return {k.lower(): v for k, v in zip(flat[::2], flat[1::2], strict=False)}


def part(data: dict[bytes, Any], key: bytes) -> bytes:
    """A fetched body section. Servers may spell the key a little
    differently, so the start is enough."""
    for name, value in data.items():
        if isinstance(name, bytes) and name.startswith(key):
            return bytes(value or b"")
    return b""


def new_uids(reported: list[Any]) -> dict[int, int]:
    """Old UID to new, from ``COPYUID <validity> <old set> <new set>``."""
    found: dict[int, int] = {}
    for item in reported:
        said = text(item) if isinstance(item, bytes | str) else ""
        match = re.search(r"(?:COPYUID )?\d+ ([\d:,]+) ([\d:,]+)", said)
        if match is None:
            continue
        old, new = uid_set(match.group(1)), uid_set(match.group(2))
        if len(old) == len(new):
            found.update(zip(old, new, strict=True))
    return found


def uid_set(value: str) -> list[int]:
    """``3:5,9`` to ``[3, 4, 5, 9]``, in the order given."""
    uids: list[int] = []
    for piece in value.split(","):
        first, _, last = piece.partition(":")
        start, end = int(first), int(last or first)
        step = 1 if end >= start else -1
        uids += range(start, end + step, step)
    return uids


def with_code(client: Any, code: str, command: Callable[[], Any]) -> list[Any]:
    """Run a command and return the response code it produced, e.g. the
    ``[COPYUID ...]`` of a move, or else the command's own answer. imaplib
    files such codes in the client's untagged responses. This is the one
    place that reaches into it."""
    codes = client._imap.untagged_responses
    codes.pop(code, None)
    answer = command()
    found: list[Any] = codes.pop(code, None) or [answer]
    return found


def thread_headers(header_block: bytes) -> fields.ThreadHeaders:
    return fields.thread_headers(BytesHeaderParser().parsebytes(header_block).get)


def quietly(command: Callable[[], Any]) -> None:
    """A command whose failure changes nothing, e.g. dropping a subscription
    that does not exist."""
    with suppress(imaplib.IMAP4.error):
        command()


def quietly_logout(client: Any) -> None:
    with suppress(imaplib.IMAP4.error, OSError):
        client.logout()


def uidvalidity(answer: Any) -> int:
    """What SELECT reported. A server must report it (RFC 3501), and
    without it no id of this adapter can be made."""
    value = answer.get(b"UIDVALIDITY")
    if value is None:
        raise ProviderError("the mail server reported no UIDVALIDITY")
    return int(value)
