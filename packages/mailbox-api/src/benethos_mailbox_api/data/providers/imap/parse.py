"""A fetched message, parsed. The only module that imports ``imap_tools``.

imap-tools is used here for its mail parser only: headers decoded, addresses,
dates, text and HTML bodies with broken charsets handled, attachments. The
protocol is spoken by ``client``. Replacing the parser, e.g. with the
standard library's ``email``, rewrites this module and nothing else.
"""

from __future__ import annotations

from typing import Any

from imap_tools import MailMessage


class FetchedMessage:
    """UID and flags as the server reported them, the rest parsed from the
    fetched bytes: ``subject``, ``from_values``, ``to_values``, ``date``,
    ``headers``, ``text``, ``html``, ``attachments`` and so on."""

    def __init__(self, uid: int, flags: tuple[str, ...], raw: bytes) -> None:
        self.uid = str(uid)
        self.flags = flags
        self._parsed = MailMessage.from_bytes(raw)

    def __getattr__(self, name: str) -> Any:
        return getattr(self._parsed, name)
