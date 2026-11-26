"""Names a database server takes without quoting: a role, and the schema
named after it, which stands in the search path of a connection."""

from __future__ import annotations

import re

# Lower case letters, digits and underscores, not first a digit, as long
# as PostgreSQL keeps a name.
_PLAIN_NAME = re.compile(r"[a-z_][a-z0-9_]{0,62}")


def is_plain_name(text: str) -> bool:
    """Whether ``text`` is a name the server takes without quoting."""
    return _PLAIN_NAME.fullmatch(text) is not None
