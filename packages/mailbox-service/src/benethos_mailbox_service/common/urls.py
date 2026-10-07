"""URLs, read one way: where they point and what of them goes on. Host
names alone are ``hosts``."""

from __future__ import annotations

from ipaddress import ip_address
from urllib.parse import urlsplit


def host_of(url: str) -> str | None:
    """The host ``url`` names, lower case. None when it names none or is
    no URL. Enough to name a URL in the log, which must not hold the whole
    of it: a path or a query may carry a key."""
    try:
        return urlsplit(url).hostname or None
    except ValueError:
        return None


def is_loopback(url: str) -> bool:
    """Whether ``url`` names this computer: localhost or a loopback
    address."""
    host = host_of(url) or ""
    if host == "localhost":
        return True
    try:
        return ip_address(host).is_loopback
    except ValueError:
        return False


def path_and_query(url: str) -> str:
    """The path of ``url`` with its query, without the scheme and the
    host: ``/a/b?c=d``."""
    parts = urlsplit(url)
    return f"{parts.path}?{parts.query}" if parts.query else parts.path
