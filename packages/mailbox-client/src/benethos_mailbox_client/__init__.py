"""mailbox-client, the Python client of the REST API of mailbox-service.

``MailboxClient`` is for async code, ``SyncMailboxClient`` for code
without an event loop. Both send the same requests and answer the same
records."""

from __future__ import annotations

from importlib.metadata import PackageNotFoundError, version

from .client import MailboxClient
from .endpoints import message_body
from .errors import (
    ApiError,
    ConfigurationError,
    MailboxError,
    ServiceTimeoutError,
    ServiceUnavailableError,
)
from .models import (
    Attachment,
    Changes,
    Folder,
    Me,
    MeAccount,
    Outcome,
    Page,
    Recipient,
    Sending,
    Sent,
)
from .sync import SyncMailboxClient
from .wire import Environment, from_environment, service_url

try:
    __version__ = version("benethos-mailbox-client")
except PackageNotFoundError:  # pragma: no cover - running from a bare tree
    __version__ = "0.0.0"

__all__ = [
    "ApiError",
    "Attachment",
    "Changes",
    "ConfigurationError",
    "Environment",
    "Folder",
    "MailboxClient",
    "MailboxError",
    "Me",
    "MeAccount",
    "Outcome",
    "Page",
    "Recipient",
    "Sending",
    "Sent",
    "ServiceTimeoutError",
    "ServiceUnavailableError",
    "SyncMailboxClient",
    "__version__",
    "from_environment",
    "message_body",
    "service_url",
]
