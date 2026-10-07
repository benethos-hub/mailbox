"""An attachment's bytes, read in chunks up to the caller's limit, and
what the answer's headers say of it: its type, its charset and its file
name. Both clients collect the chunks here, each in its own way."""

from __future__ import annotations

import codecs
import re
from urllib.parse import unquote

import httpx

from .models import Attachment


class Collected:
    """The bytes of an answer read in chunks, up to a limit. ``add``
    answers False once the limit is passed: reading stops there."""

    def __init__(self, max_bytes: int) -> None:
        self.max_bytes = max_bytes
        self.chunks: list[bytes] = []
        self.read = 0
        self.complete = True

    def add(self, chunk: bytes) -> bool:
        self.chunks.append(chunk)
        self.read += len(chunk)
        if self.read > self.max_bytes:
            self.complete = False
        return self.complete


def attachment(headers: httpx.Headers, collected: Collected) -> Attachment:
    """The attachment the headers describe, with the bytes read of it."""
    media, _, options = headers.get(
        "content-type", "application/octet-stream"
    ).partition(";")
    charset = re.search(r"charset=\"?([\w.:-]+)", options)
    name = re.search(
        r"filename\*=UTF-8''([^;]+)", headers.get("content-disposition", "")
    )
    return Attachment(
        data=b"".join(collected.chunks)[: collected.max_bytes],
        content_type=_media_type(media),
        charset=_known_charset(charset.group(1)) if charset else None,
        filename=unquote(name.group(1)) if name else None,
        complete=collected.complete,
    )


# A media type, type/subtype in the characters RFC 6838 allows. The sender
# of a mail chose it, and a caller may show it.
_MEDIA_TYPE = re.compile(r"[a-z0-9][a-z0-9!#$&^_.+-]*/[a-z0-9][a-z0-9!#$&^_.+-]*")


def _media_type(value: str) -> str:
    """``value`` when it is a media type and nothing else, else the type of
    unknown bytes."""
    media = value.strip().lower()
    if len(media) <= 127 and _MEDIA_TYPE.fullmatch(media):
        return media
    return "application/octet-stream"


def _known_charset(name: str) -> str | None:
    try:
        codecs.lookup(name)
    except LookupError:
        return None
    return name
