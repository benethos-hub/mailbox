"""Host names, written one way: lower case, no trailing dot, in ASCII.

A host a user typed or a document named may be in Unicode (``bücher.de``)
or in punycode (``xn--bcher-kva.de``). Compared, looked up or put into a
URL, it is the ASCII form. Shown to a person, it is the Unicode form.
"""

from __future__ import annotations

import ipaddress
import re

# One label in ASCII: letters, digits, inner hyphens.
_LABEL = re.compile(r"(?!-)[a-z0-9-]{1,63}(?<!-)")
# The top-level label: letters, or an internationalised one in punycode.
_TOP = re.compile(r"[a-z]{2,63}|xn--[a-z0-9-]{1,59}")
LONGEST = 253
# The longest address SMTP carries (RFC 5321 4.5.3.1.3).
LONGEST_ADDRESS = 254
# Whitespace and control characters, in no address and no host. ``\s``
# holds the line breaks beyond ASCII as well, U+2028 among them.
_BLANK = re.compile(r"[\s\x00-\x1f\x7f]")


def ascii_host(host: str) -> str | None:
    """``host`` in lower case, without a trailing dot, in punycode. None
    when it is no name IDNA can write, such as an empty label or a
    broken ``xn--`` label."""
    host = host.strip().lower().rstrip(".")
    try:
        written = host.encode("idna").decode("ascii")
        written.encode("ascii").decode("idna")
    except UnicodeError:
        return None
    return written


def unicode_host(host: str) -> str:
    """``host`` as a person reads it, punycode decoded. Unchanged when it
    cannot be decoded."""
    try:
        return host.encode("ascii").decode("idna")
    except UnicodeError:
        return host


def is_host_name(host: str, *, dotted: bool = True) -> bool:
    """Whether ``host``, already in ASCII, is a name in the DNS: labels of
    letters, digits and inner hyphens, at most 253 characters. A port or a
    path is none. ``dotted`` also asks for two labels at least and a
    top-level label of letters, as the name of a server: an IP address is
    none then."""
    labels = host.split(".")
    if len(host) > LONGEST or not all(_LABEL.fullmatch(x) for x in labels):
        return False
    return not dotted or (len(labels) >= 2 and _TOP.fullmatch(labels[-1]) is not None)


def is_server(host: str) -> bool:
    """Whether ``host`` can name a server to connect to: a name in the DNS,
    in Unicode or in ASCII, or an IP address. A port, a path, a blank or
    a control character is none."""
    if _BLANK.search(host):
        return False
    try:
        ipaddress.ip_address(host)
    except ValueError:
        pass
    else:
        return True
    written = ascii_host(host)
    return written is not None and is_host_name(written, dotted=False)


def address_problem(email: str) -> str | None:
    """Why ``email`` is no address to connect or look up, None when it is
    one: a local part without blanks or control characters, and a domain
    that is a name in the DNS."""
    local, at, domain = email.rpartition("@")
    if (
        not at
        or not local
        or not domain
        or len(email) > LONGEST_ADDRESS
        or _BLANK.search(email)
    ):
        return "not a valid email address"
    written = ascii_host(domain)
    if written is None or not is_host_name(written, dotted=False):
        return "not a valid email domain"
    return None
