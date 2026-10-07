"""Provider-neutral data model, split by subject.

Every provider adapter maps into these types, the domain works with them, and
the web layer serves them. They know nothing of HTTP, SQL or any mail protocol.
Callers import from here, not the modules.
"""

from __future__ import annotations

from .accounts import (
    Account,
    AccountStatus,
    Capability,
    CredentialInfo,
    ProviderType,
)
from .audit import (
    ActivityFilter,
    ActivityOutcome,
    ActivityRecord,
    SendFilter,
    SendOutcome,
    SendRecord,
)
from .batch import BatchItemResult, BatchResult, ItemError, MessageBatch
from .changes import (
    FEED_KINDS,
    Change,
    ChangeKind,
    ChangePage,
    ChangeRecord,
    FeedKind,
)
from .discovery import (
    Candidate,
    CredentialKind,
    Discovery,
    DiscoverySourceName,
    Hint,
    MailServer,
    Security,
    ServerProtocol,
    SourceOutcome,
    SourceReport,
)
from .folders import Folder, FolderCreate, FolderRole, FolderUpdate
from .messages import (
    SEARCH_TEXT_PATTERN,
    Address,
    Attachment,
    AttachmentContent,
    Message,
    MessageFilter,
    MessageSummary,
    MessageUpdate,
)
from .paging import AccountFailure, Before, MessagePage, Page
from .sending import (
    DraftMessage,
    MessageReference,
    OutgoingAttachment,
    OutgoingMessage,
    Recipient,
    SendResult,
    SentMessage,
)
from .users import SERVICE_DESCRIPTION, ApiToken, Grant, Role, User
from .webhooks import (
    CHANGE_KINDS,
    CreatedWebhook,
    Webhook,
    WebhookCreate,
    WebhookDetail,
    WebhookPost,
)

__all__ = [
    "ActivityFilter",
    "ActivityOutcome",
    "ActivityRecord",
    "Account",
    "AccountFailure",
    "Before",
    "AccountStatus",
    "Capability",
    "Address",
    "ApiToken",
    "Attachment",
    "AttachmentContent",
    "BatchItemResult",
    "BatchResult",
    "Candidate",
    "CHANGE_KINDS",
    "Change",
    "ChangeKind",
    "ChangePage",
    "ChangeRecord",
    "CredentialInfo",
    "CredentialKind",
    "Discovery",
    "DiscoverySourceName",
    "DraftMessage",
    "FEED_KINDS",
    "FeedKind",
    "Folder",
    "FolderCreate",
    "FolderRole",
    "FolderUpdate",
    "Grant",
    "SERVICE_DESCRIPTION",
    "Hint",
    "ItemError",
    "MailServer",
    "Message",
    "MessageBatch",
    "MessageFilter",
    "MessagePage",
    "MessageReference",
    "MessageSummary",
    "MessageUpdate",
    "OutgoingAttachment",
    "OutgoingMessage",
    "Page",
    "ProviderType",
    "Recipient",
    "Role",
    "SEARCH_TEXT_PATTERN",
    "Security",
    "SendFilter",
    "SendOutcome",
    "SendRecord",
    "SendResult",
    "SentMessage",
    "ServerProtocol",
    "SourceOutcome",
    "SourceReport",
    "User",
    "CreatedWebhook",
    "Webhook",
    "WebhookCreate",
    "WebhookDetail",
    "WebhookPost",
]
