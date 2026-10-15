"""Single header fields as this project writes them, whichever parser or
protocol produced them."""

from __future__ import annotations

import re
from collections.abc import Callable
from dataclasses import dataclass

from ...errors import BadRequestError

# The content type of an attachment that names none.
OCTET_STREAM = "application/octet-stream"


def message_id(value: object) -> str | None:
    """A ``Message-ID`` as one token: the first ``<...>`` of the header,
    without the spaces and line breaks a fold left in it. A header without
    one is taken whole, without spaces. None for an empty value."""
    return next(iter(message_ids(value)), None) or _joined(value)


def message_ids(value: object) -> list[str]:
    """The ``Message-ID`` tokens of a header that lists them, such as
    References or In-Reply-To, whether folded or not: each ``<...>``,
    leaving out comments and words between them. A header without one
    is split at its spaces."""
    text = str(value or "")
    found = [_joined(token) for token in _BRACKETED.findall(text)]
    return [token for token in found if token] or text.split()


# A message id in angle brackets, which a fold may have broken.
_BRACKETED = re.compile(r"<[^<>]*>")


def _joined(value: object) -> str | None:
    return "".join(str(value or "").split()) or None


@dataclass(frozen=True, slots=True)
class ThreadHeaders:
    """The headers that tie a message to its conversation: its own
    ``Message-ID``, the one it answers and the ``References``, oldest
    first."""

    message_id: str | None = None
    in_reply_to: str | None = None
    references: tuple[str, ...] = ()


def thread_headers(header: Callable[[str], object]) -> ThreadHeaders:
    """The three headers, read by name with ``header``."""
    return ThreadHeaders(
        message_id(header("Message-ID")),
        next(iter(message_ids(header("In-Reply-To"))), None),
        tuple(message_ids(header("References"))),
    )


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
