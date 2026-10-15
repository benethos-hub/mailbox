"""Connected mailboxes: the account, its provider and its state."""

from __future__ import annotations

from collections.abc import Iterable
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
    """What an account can do beyond reading its inbox, each guarding one
    thing (docs/UNIFORM.md section 3). Where one is missing, the operations
    that need it answer `501 not_supported`. They follow from what the
    account's server offers."""

    # `unread` is kept and can be set.
    READ_STATE = "read_state"
    # `starred` is kept and can be set.
    STARS = "stars"
    # Own keywords, without `$`.
    KEYWORDS = "keywords"
    # Folders: create, rename, delete.
    FOLDERS = "folders"
    # Moving messages between folders.
    MOVE = "move"
    # Deleting into the trash.
    TRASH = "trash"
    # Deleting for good.
    PURGE = "purge"
    # A message can sit in several folders at once.
    LABELS = "labels"
    # The filters of a list: text, sender, date, unread, ...
    SEARCH = "search"
    DRAFTS = "drafts"
    SEND = "send"
    # A sent mail is kept and its id answered.
    SENT_COPY = "sent_copy"
    # Messages carry the thread of their conversation, across folders.
    THREADS = "threads"
    # Changes arrive within seconds, without polling.
    PUSH = "push"
    # The change feed sees read state, stars and keywords changed by other
    # clients.
    EXTERNAL_CHANGES = "external_changes"
    # A send names the recipients the server refused at once. Without it
    # they come back later as a bounce mail, and `refused` stays empty.
    REFUSED = "refused"


class Mark(StrEnum):
    """The keywords of RFC 8621 besides `$seen` and `$flagged`, which are
    `unread` and `starred`. Other `$` keywords are keywords."""

    ANSWERED = "$answered"
    FORWARDED = "$forwarded"
    DRAFT = "$draft"
    JUNK = "$junk"
    NOTJUNK = "$notjunk"
    PHISHING = "$phishing"


class Marks(BaseModel):
    """Which marks an account reads and which it writes. A mark it does not
    read never appears, and its absence means nothing. Writing one it does
    not write answers `501`."""

    read: list[Mark] = Field(default_factory=list)
    written: list[Mark] = Field(default_factory=list)


class Abilities(BaseModel):
    """What an account can do, as its server answered when it was connected
    or verified. Stored with the account."""

    capabilities: list[Capability] = Field(default_factory=list)
    marks: Marks = Field(default_factory=Marks)

    def has(self, capability: Capability) -> bool:
        return capability in self.capabilities

    @classmethod
    def of(
        cls,
        capabilities: Iterable[Capability],
        read: Iterable[Mark] = (),
        written: Iterable[Mark] = (),
    ) -> Abilities:
        """Sorted, each once. What is written is read as well."""
        written = set(written)
        return cls(
            capabilities=sorted(set(capabilities)),
            marks=Marks(read=sorted(set(read) | written), written=sorted(written)),
        )


class AccountStatus(StrEnum):
    CONNECTED = "connected"
    NEEDS_REAUTH = "needs_reauth"
    UNREACHABLE = "unreachable"


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
            "What the account can do beyond reading its inbox, as its server "
            "answered when the account was connected or verified. An "
            "operation that needs a capability the account lacks answers "
            "`501`. A POP3 account has no `read_state`, `folders` or "
            "`search`, for example. Empty until the server was asked once."
        ),
    )
    marks: Marks = Field(
        default_factory=Marks,
        description=(
            "The marks of RFC 8621 the account reads and those it writes, "
            "such as `$answered`. Adding or taking off a mark it does not "
            "write answers `501`."
        ),
    )
