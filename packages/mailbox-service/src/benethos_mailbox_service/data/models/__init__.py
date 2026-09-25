"""Provider-neutral data model, split by subject.

Every provider adapter maps into these types, the domain works with them, and
the web layer serves them. They know nothing of HTTP, SQL or any mail protocol.
Callers import from here, not the modules.
"""

from __future__ import annotations

from .accounts import Account, AccountStatus, CredentialInfo, ProviderType
from .audit import SendOutcome, SendRecord
from .batch import BatchItemResult, BatchResult, ItemError, MessageBatch
from .changes import (
    CHANGE_TYPES,
    Change,
    ChangePage,
    ChangeType,
    Event,
    EventType,
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
    Address,
    Attachment,
    AttachmentContent,
    Message,
    MessageFilter,
    MessageSummary,
    MessageUpdate,
)
from .paging import AccountFailure, MessagePage, Page
from .sending import (
    DraftMessage,
    MessageReference,
    OutgoingAttachment,
    OutgoingMessage,
    Recipient,
    SendResult,
    SentMessage,
)
from .users import ApiToken, Grant, Role, User

__all__ = [
    "Account",
    "AccountFailure",
    "AccountStatus",
    "Address",
    "ApiToken",
    "Attachment",
    "AttachmentContent",
    "BatchItemResult",
    "BatchResult",
    "Candidate",
    "CHANGE_TYPES",
    "Change",
    "ChangePage",
    "ChangeType",
    "CredentialInfo",
    "CredentialKind",
    "Discovery",
    "DiscoverySourceName",
    "DraftMessage",
    "Event",
    "EventType",
    "Folder",
    "FolderCreate",
    "FolderRole",
    "FolderUpdate",
    "Grant",
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
    "Security",
    "SendOutcome",
    "SendRecord",
    "SendResult",
    "SentMessage",
    "ServerProtocol",
    "SourceOutcome",
    "SourceReport",
    "User",
]
