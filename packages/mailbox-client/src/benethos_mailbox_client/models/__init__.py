"""The records the client answers with: small, frozen, in the terms of
a caller rather than the fields of the API."""

from __future__ import annotations

from .accounts import Account, StoredCredential
from .audit import Activity
from .discovery import (
    Candidate,
    DeviceSignIn,
    DeviceSignInState,
    Discovery,
    Hint,
    MailServer,
    SourceReport,
)
from .factors import SecondFactor, TotpDevice
from .folders import Folder
from .health import Health
from .me import Me, MeAccount, Sending
from .messages import (
    Address,
    AttachedFile,
    Attachment,
    Change,
    Changes,
    Failed,
    Message,
    MessageSummary,
    Outcome,
    Page,
    Reference,
)
from .paging import Paged
from .rights import Grant, Permissions
from .roles import Role
from .secrets import Secret
from .sending import Recipient, Sent
from .sends import SendRecord
from .status import AccountHealth, Status, Worker
from .tokens import NewToken, Token
from .users import NewPassword, User
from .webhooks import NewWebhook, Webhook, WebhookDetail, WebhookPost, WebhookSecret

__all__ = [
    "Health",
    "Permissions",
    "Worker",
    "Status",
    "AccountHealth",
    "SendRecord",
    "Activity",
    "NewWebhook",
    "WebhookDetail",
    "WebhookPost",
    "TotpDevice",
    "SecondFactor",
    "Role",
    "Token",
    "NewToken",
    "User",
    "NewPassword",
    "Grant",
    "SourceReport",
    "MailServer",
    "Hint",
    "Discovery",
    "DeviceSignInState",
    "DeviceSignIn",
    "Candidate",
    "StoredCredential",
    "Account",
    "Paged",
    "Address",
    "AttachedFile",
    "Attachment",
    "Message",
    "MessageSummary",
    "Reference",
    "Change",
    "Changes",
    "Failed",
    "Folder",
    "Me",
    "MeAccount",
    "Outcome",
    "Page",
    "Recipient",
    "Secret",
    "Sending",
    "Sent",
    "Webhook",
    "WebhookSecret",
]
