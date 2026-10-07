"""JMAP (RFC 8620, 8621) over ``http``: the session, method calls, blobs
and the event stream (``client``), what the server sends as shapes
(``shapes``), and its answers and errors read (``answers``).

Speaks the protocol and nothing else: no folders or messages of the API,
no decisions. JMAP's own errors leave it as ``MailboxServiceError``.

Every URL the session names is used on the server the account names: its
path and query, never its host or port. So the credential goes to no other
host, and a server that names itself otherwise, behind a proxy or by a
name only its own network knows, still works.
"""

from __future__ import annotations

from .answers import error_type, method_error, read, result, set_error
from .client import (
    CORE,
    DEFAULT_CALLS,
    DEFAULT_CONCURRENT,
    DEFAULT_GET,
    DEFAULT_PATH,
    DEFAULT_PORT,
    MAIL,
    MAX_REDIRECTS,
    SUBMISSION,
    JmapClient,
    JmapServer,
    Session,
    is_session,
)
from .shapes import (
    Anything,
    Changed,
    Created,
    Got,
    Invocation,
    Queried,
    SetError,
    SetResult,
    States,
)

__all__ = [
    "CORE",
    "DEFAULT_CALLS",
    "DEFAULT_CONCURRENT",
    "DEFAULT_GET",
    "DEFAULT_PATH",
    "DEFAULT_PORT",
    "MAIL",
    "MAX_REDIRECTS",
    "SUBMISSION",
    "Anything",
    "Changed",
    "Created",
    "Got",
    "Invocation",
    "JmapClient",
    "JmapServer",
    "Queried",
    "Session",
    "SetError",
    "SetResult",
    "States",
    "error_type",
    "is_session",
    "method_error",
    "read",
    "result",
    "set_error",
]
