"""Provider-neutral data model.

Every provider adapter maps into these types, the domain works with them, and
the web layer serves them. They know nothing of HTTP, SQL or any mail protocol.
"""

from __future__ import annotations

from datetime import datetime
from enum import StrEnum
from typing import Annotated, Generic, TypeVar

from pydantic import BaseModel, Field


class ProviderType(StrEnum):
    IMAP = "imap"
    GMAIL = "gmail"
    MICROSOFT = "microsoft"
    MEMORY = "memory"


class AccountStatus(StrEnum):
    CONNECTED = "connected"
    NEEDS_REAUTH = "needs_reauth"
    UNREACHABLE = "unreachable"
    DISABLED = "disabled"


class FolderRole(StrEnum):
    """Special-use role, after RFC 6154 and JMAP."""

    INBOX = "inbox"
    SENT = "sent"
    DRAFTS = "drafts"
    TRASH = "trash"
    JUNK = "junk"
    ARCHIVE = "archive"
    ALL = "all"


class Address(BaseModel):
    email: str
    name: str | None = None


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


class Grant(BaseModel):
    """Rights on accounts: operation or group names, account ids or ``*``."""

    accounts: list[str]
    allow: list[str]


class User(BaseModel):
    """Someone or something that calls the API."""

    id: str
    name: str
    roles: list[str] = Field(default_factory=list)
    grants: list[Grant] = Field(default_factory=list)
    disabled: bool = False


class Role(BaseModel):
    """A named, reusable set of grants."""

    id: str
    grants: list[Grant] = Field(default_factory=list)


class ApiToken(BaseModel):
    """An API token of a user. Only the SHA-256 hash of the token is kept."""

    id: str
    user_id: str
    name: str
    token_hash: str
    created_at: datetime
    expires_at: datetime | None = None
    last_used_at: datetime | None = None
    revoked_at: datetime | None = None


class Folder(BaseModel):
    id: str
    name: str
    role: FolderRole | None = None
    parent_id: str | None = None
    total: int | None = None
    unread: int | None = None
    subscribed: bool | None = Field(
        default=None,
        description=(
            "Whether the folder is subscribed on the server (IMAP). Mail "
            "clients such as Outlook show only subscribed folders, and the "
            "inbox always. Null where the provider has no subscriptions."
        ),
    )


class MessageSummary(BaseModel):
    id: str
    account_id: str | None = None
    thread_id: str | None = None
    folder_ids: list[str] = Field(default_factory=list)
    subject: str | None = None
    sender: Address | None = Field(default=None, alias="from")
    to: list[Address] = Field(default_factory=list)
    date: datetime | None = None
    snippet: str | None = None
    unread: bool = False
    starred: bool = False
    keywords: list[str] = Field(
        default_factory=list,
        description=(
            "Further flags, named as in JMAP: `$answered`, `$forwarded`, "
            "`$draft`, and the provider's own keywords."
        ),
    )
    has_attachments: bool = False

    model_config = {"populate_by_name": True, "serialize_by_alias": True}


# A keyword as IMAP allows it: an atom, no spaces, brackets, quotes or
# wildcards, and no system flag (those start with a backslash).
KEYWORD_PATTERN = r"^[!#$&'+\-.0-9A-Z^_a-z|~]{1,100}$"


class MessageUpdate(BaseModel):
    """What ``PATCH`` changes on a message. Fields left out stay as they are."""

    unread: bool | None = None
    starred: bool | None = None
    keywords: list[Annotated[str, Field(pattern=KEYWORD_PATTERN)]] | None = Field(
        default=None,
        max_length=50,
        description="Replaces the list of keywords.",
    )
    folder_ids: list[str] | None = Field(
        default=None,
        min_length=1,
        max_length=20,
        description=(
            "The folders the message is to be in. A change moves it; the id "
            "stays. An IMAP message is in exactly one folder."
        ),
    )


class Attachment(BaseModel):
    id: str
    filename: str | None = None
    content_type: str
    size: int
    inline: bool = False


class AttachmentContent(BaseModel):
    """An attachment with its bytes, for download."""

    filename: str | None = None
    content_type: str
    data: bytes


class Message(MessageSummary):
    cc: list[Address] = Field(default_factory=list)
    bcc: list[Address] = Field(default_factory=list)
    reply_to: list[Address] = Field(default_factory=list)
    message_id_header: str | None = None
    in_reply_to: str | None = None
    text_body: str | None = None
    html_body: str | None = None
    attachments: list[Attachment] = Field(default_factory=list)


T = TypeVar("T")


class Page(BaseModel, Generic[T]):
    """One page of a list. ``next_cursor`` is opaque, absent on the last page."""

    items: list[T]
    next_cursor: str | None = None


class AccountFailure(BaseModel):
    """An account that could not answer, in a list across accounts."""

    account_id: str
    code: str
    message: str


class MessagePage(Page[MessageSummary]):
    """Messages across accounts. ``incomplete`` names the accounts that did
    not answer; their messages are missing from this page."""

    incomplete: list[AccountFailure] = Field(default_factory=list)


# --- Autodiscovery (CONCEPT 5.8) ---------------------------------------------


class DiscoverySourceName(StrEnum):
    PRESET = "preset"
    AUTOCONFIG = "autoconfig"
    ISPDB = "ispdb"
    MX = "mx"


class ServerProtocol(StrEnum):
    IMAP = "imap"
    SMTP = "smtp"


class Security(StrEnum):
    """Encryption of a mail server connection. Plain text is never offered."""

    TLS = "tls"
    STARTTLS = "starttls"


class CredentialKind(StrEnum):
    """What to ask the person for."""

    PASSWORD = "password"
    APP_PASSWORD = "app_password"
    OAUTH = "oauth"


class MailServer(BaseModel):
    protocol: ServerProtocol
    host: str
    port: int
    security: Security
    # The login name. In a candidate the address is filled in; sources may
    # hand in a template with %EMAILADDRESS%, %EMAILLOCALPART%, %EMAILDOMAIN%.
    username: str | None = None
    # Whether an anonymous connection succeeded. None: not tried.
    reachable: bool | None = None
    # What the server announced before any login, e.g. IDLE, AUTH=XOAUTH2.
    capabilities: list[str] = Field(default_factory=list)


class Hint(BaseModel):
    """Something the person has to know or do, with a help page if known."""

    text: str
    url: str | None = None


class Candidate(BaseModel):
    """One way to connect an address, as found by one source."""

    provider: ProviderType
    name: str | None = None
    credential: CredentialKind
    # "google" or "microsoft" when the credential is an OAuth sign-in.
    oauth_provider: str | None = None
    servers: list[MailServer] = Field(default_factory=list)
    hints: list[Hint] = Field(default_factory=list)
    source: DiscoverySourceName
    # True when the answer comes from our presets or from the address's own
    # domain. Anything else needs an explicit yes from the person.
    confirmed: bool = False
    # Ready for POST /v1/accounts, next to the credential.
    settings: dict[str, str | int | bool] = Field(default_factory=dict)


class SourceOutcome(StrEnum):
    FOUND = "found"
    NOTHING = "nothing"
    FAILED = "failed"


class SourceReport(BaseModel):
    source: DiscoverySourceName
    outcome: SourceOutcome
    message: str | None = None


class Discovery(BaseModel):
    """Ranked ways to connect an address, best first."""

    email: str
    domain: str
    candidates: list[Candidate] = Field(default_factory=list)
    # Notes that hold for the address whatever the candidate, e.g. that the
    # provider offers no access for other programs.
    hints: list[Hint] = Field(default_factory=list)
    sources: list[SourceReport] = Field(default_factory=list)
