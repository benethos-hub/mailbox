"""IMAP, the only package that imports ``imapclient``.

Synchronous, like the library. The adapter runs a session in a worker
thread and never calls it from two threads at once. Every library error
leaves this package as a ``MailboxServiceError``. What is fetched of a
message is parsed in ``data.mail.parse``. This package only speaks the
protocol.

``session`` holds the connection, the login, the selected folder and
IDLE. Its parts: ``folders`` and ``messages``. ``responses`` reads what
the server answers, ``values`` holds what a session hands out.
"""

from __future__ import annotations

from ..transport import Server
from .folders import Folders
from .messages import Messages
from .session import IDLE_STEP, ClientFactory, ImapSession, default_client
from .values import (
    DEFAULT_PORTS,
    MAX_HEADER_BYTES,
    MAX_MESSAGE_BYTES,
    FetchedMessage,
    RawFolder,
    SearchCriteria,
)

__all__ = [
    "DEFAULT_PORTS",
    "IDLE_STEP",
    "MAX_HEADER_BYTES",
    "MAX_MESSAGE_BYTES",
    "ClientFactory",
    "FetchedMessage",
    "Folders",
    "ImapSession",
    "Messages",
    "RawFolder",
    "SearchCriteria",
    "Server",
    "default_client",
]
