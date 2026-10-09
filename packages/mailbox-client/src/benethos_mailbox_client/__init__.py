"""mailbox-client, the Python client of the REST API of mailbox-service.

``MailboxClient`` is for async code, ``SyncMailboxClient`` for code
without an event loop. Both send the same requests and answer the same
records."""

from __future__ import annotations

from importlib.metadata import PackageNotFoundError, version

from .client import MailboxClient
from .endpoints import message_body
from .environment import Environment, from_environment
from .errors import (
    ApiError,
    ConfigurationError,
    MailboxError,
    ServiceTimeoutError,
    ServiceUnavailableError,
)
from .models import (
    Account,
    Activity,
    Attachment,
    Candidate,
    Changes,
    DeviceSignIn,
    DeviceSignInState,
    Discovery,
    Folder,
    Grant,
    Hint,
    MailServer,
    Me,
    MeAccount,
    NewPassword,
    NewToken,
    NewWebhook,
    Outcome,
    Page,
    Paged,
    Recipient,
    Role,
    SecondFactor,
    Secret,
    Sending,
    SendRecord,
    Sent,
    SourceReport,
    StoredCredential,
    Token,
    TotpDevice,
    User,
    Webhook,
    WebhookDetail,
    WebhookPost,
    WebhookSecret,
)
from .sync import SyncMailboxClient

try:
    __version__ = version("benethos-mailbox-client")
except PackageNotFoundError:  # pragma: no cover - running from a bare tree
    __version__ = "0.0.0"

__all__ = [
    "SendRecord",
    "Activity",
    "NewWebhook",
    "WebhookDetail",
    "WebhookPost",
    "SecondFactor",
    "TotpDevice",
    "Role",
    "NewToken",
    "Token",
    "NewPassword",
    "User",
    "Grant",
    "Candidate",
    "DeviceSignIn",
    "DeviceSignInState",
    "Discovery",
    "Hint",
    "MailServer",
    "SourceReport",
    "Account",
    "StoredCredential",
    "Paged",
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
    "Secret",
    "Sending",
    "Sent",
    "ServiceTimeoutError",
    "ServiceUnavailableError",
    "SyncMailboxClient",
    "Webhook",
    "WebhookSecret",
    "__version__",
    "from_environment",
    "message_body",
]
