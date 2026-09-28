"""Host names, written one way: lower case, no trailing dot, in ASCII.

A host a user typed or a document named may be in Unicode (``bücher.de``)
or in punycode (``xn--bcher-kva.de``). Compared, looked up or put into a
URL, it is the ASCII form. Shown to a person, it is the Unicode form.
"""

from __future__ import annotations

import re

# One label in ASCII: letters, digits, inner hyphens.
_LABEL = re.compile(r"(?!-)[a-z0-9-]{1,63}(?<!-)")
# The top-level label: letters, or an internationalised one in punycode.
_TOP = re.compile(r"[a-z]{2,63}|xn--[a-z0-9-]{1,59}")
LONGEST = 253


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
