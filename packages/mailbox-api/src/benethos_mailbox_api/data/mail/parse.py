"""A message's bytes, parsed. The only module that imports ``imap_tools``.

imap-tools is used here for its mail parser only: headers decoded, addresses,
dates, text and HTML bodies with broken charsets handled, attachments. It
speaks no protocol here; the bytes come from IMAP, POP3 or anywhere else.
Replacing the parser, e.g. with the standard library's ``email``, rewrites
this module and nothing else.
"""

from __future__ import annotations

from typing import Any

from imap_tools import MailMessage


class ParsedMessage:
    """The parts of a message: ``subject``, ``from_values``, ``to_values``,
    ``date``, ``headers``, ``text``, ``html``, ``attachments`` and so on."""

    def __init__(self, raw: bytes) -> None:
        self._parsed = MailMessage.from_bytes(raw)

    def __getattr__(self, name: str) -> Any:
        return getattr(self._parsed, name)
