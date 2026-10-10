"""An address as people read it: ``Name <email>``, or the email alone.
Not the header of a message, which ``email.utils.formataddr`` writes,
encoding a name beyond ASCII."""

from __future__ import annotations


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
