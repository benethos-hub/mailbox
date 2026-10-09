"""The records the client answers with: small, frozen, in the terms of
a caller rather than the fields of the API.

A message, a summary in a page and a draft are not records: they stay
the JSON of the API, which describes them in docs/openapi.json."""

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
from .me import Me, MeAccount, Sending
from .messages import Attachment, Changes, Outcome, Page
from .paging import Paged
from .rights import Grant
from .roles import Role
from .secrets import Secret
from .sending import Recipient, Sent
from .tokens import NewToken, Token
from .users import NewPassword, User
from .webhooks import NewWebhook, Webhook, WebhookDetail, WebhookPost, WebhookSecret

__all__ = [
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
    "Attachment",
    "Changes",
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
