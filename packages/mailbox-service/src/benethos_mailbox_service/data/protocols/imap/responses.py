"""What an IMAP server answers, read: capabilities, flags, body sections,
response codes, UIDs. And its errors as this project's."""

from __future__ import annotations

import imaplib
import re
from collections.abc import Callable
from contextlib import AbstractContextManager
from email.parser import BytesHeaderParser
from typing import Any

from ....errors import ProviderError, ProviderUnavailableError
from ...mail import fields
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


def message_id(header_block: bytes) -> str | None:
    return fields.message_id(
        BytesHeaderParser().parsebytes(header_block).get("Message-ID")
    )


def quietly(command: Callable[[], Any]) -> None:
    """A command whose failure changes nothing, e.g. dropping a subscription
    that does not exist."""
    try:
        command()
    except imaplib.IMAP4.error:
        pass


def quietly_logout(client: Any) -> None:
    try:
        client.logout()
    except (imaplib.IMAP4.error, OSError):
        pass


def uidvalidity(answer: Any) -> int:
    """What SELECT reported. A server must report it (RFC 3501), and
    without it no id of this adapter can be made."""
    value = answer.get(b"UIDVALIDITY")
    if value is None:
        raise ProviderError("the mail server reported no UIDVALIDITY")
    return int(value)
