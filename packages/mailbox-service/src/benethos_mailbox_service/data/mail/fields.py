"""Single header fields as this project writes them, whichever parser or
protocol produced them."""

from __future__ import annotations

from ...errors import BadRequestError

# The content type of an attachment that names none.
OCTET_STREAM = "application/octet-stream"


def message_id(value: object) -> str | None:
    """A ``Message-ID`` as one token: a folded header keeps its line breaks,
    the id itself has no spaces. None for an empty value."""
    text = "".join(str(value or "").split())
    return text or None


def message_ids(value: object) -> list[str]:
    """The ``Message-ID`` tokens of a header that lists them, such as
    References, whether folded or not."""
    return str(value or "").split()


def ascii_domain(email: str) -> str:
    """An address with its domain in punycode, as the wire wants it. The
    local part stays as written: only SMTPUTF8 carries one in Unicode."""
    local, at, domain = email.rpartition("@")
    if not at or domain.isascii():
        return email
    return f"{local}@{domain.encode('idna').decode('ascii')}"


def wire_address(email: str) -> str:
    """``ascii_domain`` for an address that must go out: a domain that
    IDNA cannot write is a bad request."""
    try:
        return ascii_domain(email)
    except UnicodeError:
        raise BadRequestError(f"the domain of {email} cannot be encoded") from None


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
