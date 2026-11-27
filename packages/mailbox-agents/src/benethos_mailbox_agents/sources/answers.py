"""What :mod:`.mailbox` does with an answer of the service before it
becomes a record: a text made sound, and a record built only of what the
API describes. Nothing here imports the client."""

from __future__ import annotations

from collections.abc import Iterator
from contextlib import contextmanager

from pydantic import ValidationError

from ..errors import MailboxRefusedError

__all__ = ["as_described", "sound", "sound_or_none"]


def sound(value: str) -> str:
    """``value`` with each lone surrogate replaced by U+FFFD. One comes from
    the JSON escape of half a pair, and it cannot be encoded as UTF-8: a
    request to the gateway or a write to the state file would raise
    outside every error of this package."""
    return "".join("�" if 0xD800 <= ord(c) <= 0xDFFF else c for c in value)


def sound_or_none(value: str | None) -> str | None:
    return None if value is None else sound(value)


@contextmanager
def as_described() -> Iterator[None]:
    """Build a record of what the service answered. The client passes the
    fields of a message on unchecked, so a value of another type raises
    while the record is built. That is a refusal, as for an answer the
    client finds unexpected: the message counts an attempt. Its text never
    holds the value, which may be a part of a mail."""
    try:
        yield
    except (ValidationError, TypeError):
        raise MailboxRefusedError(
            "the answer is not what the API describes", reason="unexpected_response"
        ) from None
