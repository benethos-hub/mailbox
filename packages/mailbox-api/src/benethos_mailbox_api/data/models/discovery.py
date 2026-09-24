"""Autodiscovery (CONCEPT 5.8): ways to connect an address, and their sources."""

from __future__ import annotations

from enum import StrEnum

from pydantic import BaseModel, Field

from .accounts import ProviderType


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
