"""Connected mailboxes: the account, its provider and its state."""

from __future__ import annotations

from datetime import datetime
from enum import StrEnum

from pydantic import BaseModel, Field


class ProviderType(StrEnum):
    IMAP = "imap"
    POP3 = "pop3"
    JMAP = "jmap"
    GMAIL = "gmail"
    MICROSOFT = "microsoft"
    MEMORY = "memory"


class Capability(StrEnum):
    """What an account's adapter can do beyond reading its inbox. Where one
    is missing, the operations that need it answer `501 not_supported`."""

    SEND = "send"
    DRAFTS = "drafts"
    # Read state, stars and keywords of a message.
    FLAGS = "flags"
    # Folders beyond the inbox: to list, create, change and move messages
    # to, the trash among them.
    FOLDERS = "folders"
    # A list narrowed by a filter: text, sender, date, unread, ...
    SEARCH = "search"
    LABELS = "labels"  # a message can sit in several folders at once
    SERVER_SEARCH = "server_search"
    PUSH = "push"  # change notifications without polling, wait_for_change
    # A message keeps its id when it is moved. Without it the domain keeps an
    # id mapping (CONCEPT 4.1).
    STABLE_IDS = "stable_ids"
    # Reports what changed in a folder since a token, folder_changes (for
    # Microsoft: Graph delta queries).
    DELTA = "delta"


class AccountStatus(StrEnum):
    CONNECTED = "connected"
    NEEDS_REAUTH = "needs_reauth"
    UNREACHABLE = "unreachable"
    DISABLED = "disabled"


class CredentialInfo(BaseModel):
    """That a credential is stored, never its value."""

    field: str
    updated_at: datetime


class Account(BaseModel):
    id: str
    provider: ProviderType
    email: str
    display_name: str | None = None
    status: AccountStatus = AccountStatus.CONNECTED
    credentials: list[CredentialInfo] = Field(default_factory=list)
    settings: dict[str, str | int | bool] = Field(
        default_factory=dict,
        description=(
            "The connection settings: host, port, security, username, "
            "smtp_host, ... Never a secret. Secrets are `credentials`."
        ),
    )
    capabilities: list[Capability] = Field(
        default_factory=list,
        description=(
            "What the account can do beyond reading its inbox. A POP3 account "
            "has no `flags`, `folders` or `search`: those operations answer "
            "`501`. Empty where the account cannot be reached through its "
            "settings."
        ),
    )
