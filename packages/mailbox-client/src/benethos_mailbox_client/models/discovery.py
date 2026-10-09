"""What discovery found for an address, and a sign-in with a code at a
provider."""

from __future__ import annotations

from dataclasses import dataclass
from datetime import datetime
from typing import Any

from .accounts import Account


@dataclass(frozen=True)
class Hint:
    """A word for a person, e.g. where to make an app password."""

    text: str
    url: str | None


@dataclass(frozen=True)
class MailServer:
    """A server a candidate names: ``protocol`` imap, pop3, smtp or jmap,
    ``security`` tls, starttls or none. ``reachable`` None: not tried."""

    protocol: str
    host: str
    port: int
    security: str
    username: str | None
    path: str | None
    reachable: bool | None
    capabilities: tuple[str, ...]


@dataclass(frozen=True)
class Candidate:
    """One way to connect the address: the kind of account, how it signs
    in (``credential``: password, app_password, api_token or oauth), where
    it was found. ``settings`` go as they are to ``create_account``."""

    provider: str
    name: str | None
    credential: str
    oauth_provider: str | None
    servers: tuple[MailServer, ...]
    hints: tuple[Hint, ...]
    source: str
    confirmed: bool
    settings: dict[str, Any]


@dataclass(frozen=True)
class SourceReport:
    """What one source of discovery answered: found, nothing or failed."""

    source: str
    outcome: str
    message: str | None


@dataclass(frozen=True)
class Discovery:
    """The ways to connect an address, the recommended one first."""

    email: str
    domain: str
    candidates: tuple[Candidate, ...]
    hints: tuple[Hint, ...]
    sources: tuple[SourceReport, ...]


@dataclass(frozen=True)
class DeviceSignIn:
    """A sign-in with a code begun: the person enters ``user_code`` at
    ``verification_uri`` before ``expires_at``. Ask again with
    ``sign_in_id`` no sooner than every ``interval`` seconds."""

    sign_in_id: str
    user_code: str
    verification_uri: str
    expires_at: datetime
    interval: int


@dataclass(frozen=True)
class DeviceSignInState:
    """Whether the person signed in: then the account, connected or
    signed in again."""

    connected: bool
    account: Account | None
