"""Single header fields as this project writes them, whichever parser or
protocol produced them."""

from __future__ import annotations

# The content type of an attachment that names none.
OCTET_STREAM = "application/octet-stream"


def message_id(value: object) -> str | None:
    """A ``Message-ID`` as one token: a folded header keeps its line breaks,
    the id itself has no spaces. None for an empty value."""
    text = "".join(str(value or "").split())
    return text or None


def unicode_address(email: str) -> str:
    """An address with an internationalised domain in Unicode: on the wire it
    travels as punycode (``xn--``), the API shows it as people write it."""
    local, at, domain = email.rpartition("@")
    if not at or "xn--" not in domain.lower():
        return email
    try:
        return f"{local}@{domain.encode('ascii').decode('idna')}"
    except UnicodeError:
        return email
