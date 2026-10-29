"""An address as people read it: ``Name <email>``, or the email alone.
Not the header of a message, which ``email.utils.formataddr`` writes,
encoding a name beyond ASCII. And the addresses a person or a model
typed, split up before they are judged."""

from __future__ import annotations

from dataclasses import dataclass
from email.utils import getaddresses


@dataclass(frozen=True, slots=True)
class Parsed:
    """An address as it was typed, not yet judged: ``email`` may be no
    address at all."""

    name: str | None
    email: str


def parsed(text: str) -> list[Parsed]:
    """The addresses in ``text``: ``Name <a@example.org>, b@example.org``,
    a semicolon between them as well as a comma. A name with a comma
    needs quotes: ``"Smith, Ann" <ann@example.org>``."""
    text = text.replace(";", ",").strip()
    if not text:
        return []
    return [Parsed(name or None, email) for name, email in getaddresses([text])]


def readable(name: str | None, email: str, *, quoted: bool = False) -> str:
    """``Name <email>``, the email alone without a name. ``quoted`` puts
    the name in a quoted string (RFC 5322), with a backslash before a
    backslash or a double quote in it, so a form reads it back as it was:
    ``"Smith, Ann" <ann@example.org>``."""
    if not name:
        return email
    if quoted:
        escaped = name.replace("\\", "\\\\").replace('"', '\\"')
        return f'"{escaped}" <{email}>'
    return f"{name} <{email}>"
