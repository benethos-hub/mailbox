"""Names a database server is reached by: a role, and the schema named
after it, which a server takes without quoting, and whether a host is
this computer."""

from __future__ import annotations

import ipaddress
import re

# Lower case letters, digits and underscores, not first a digit, as long
# as PostgreSQL keeps a name.
_PLAIN_NAME = re.compile(r"[a-z_][a-z0-9_]{0,62}")


def is_plain_name(text: str) -> bool:
    """Whether ``text`` is a name the server takes without quoting."""
    return _PLAIN_NAME.fullmatch(text) is not None


def is_loopback_host(host: str) -> bool:
    """Whether ``host`` is this computer: localhost or a loopback
    address."""
    if host.lower() == "localhost":
        return True
    try:
        return ipaddress.ip_address(host).is_loopback
    except ValueError:
        return False
