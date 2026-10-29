"""An attachment's bytes, and a link to it for another service."""

from __future__ import annotations

from dataclasses import dataclass
from datetime import datetime

from .secrets import Secret


@dataclass(frozen=True, slots=True)
class Attachment:
    """An attachment's bytes, as far as the caller's limit allowed: with
    ``complete`` False, ``data`` stops at that limit."""

    data: bytes
    content_type: str
    charset: str | None  # one Python knows, else None
    filename: str | None
    complete: bool = True


@dataclass(frozen=True, slots=True)
class AttachmentLink:
    """A link to an attachment for another service: whoever holds ``url``
    fetches the attachment once, with GET and no token, until
    ``expires_at``. Shown once, kept out of every line as a ``Secret``."""

    url: Secret
    expires_at: datetime
    content_type: str
    size: int
    filename: str | None
