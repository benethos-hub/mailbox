"""The records the client answers with: small, frozen, in the terms of
a caller rather than the fields of the API."""

from __future__ import annotations

from .accounts import Account, Marks, StoredCredential
from .attachments import Attachment, AttachmentLink
from .audit import Activity
from .changes import Change, Changes
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
from .sending import AttachmentSource, OutgoingFile, Recipient, Sent
from .sends import SendRecord
from .status import AccountHealth, Status, Worker
from .threads import Thread, ThreadSummary
from .tokens import NewToken, Token
from .users import NewPassword, User
from .webhooks import NewWebhook, Webhook, WebhookDetail, WebhookPost, WebhookSecret

__all__ = [
    "Marks",
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
    "Thread",
    "ThreadSummary",
    "Address",
    "AttachedFile",
    "AttachmentSource",
    "Attachment",
    "AttachmentLink",
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
    "OutgoingFile",
    "Page",
    "Recipient",
    "Secret",
    "Sending",
    "Sent",
    "Webhook",
    "WebhookSecret",
]
