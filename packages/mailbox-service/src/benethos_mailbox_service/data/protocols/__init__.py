"""The wire, one library each: ``imap`` (IMAPClient), ``smtp`` (smtplib),
``http`` (httpx), ``oauth`` (OAuth 2.0 over ``http``), ``pop3``
(poplib). ``transport`` holds TLS, the timeouts and the failures below
every library.

Each module speaks its protocol and nothing else: no ids, no folders of the
API, no decisions. Library errors leave it as ``MailboxServiceError``. It
imports nothing of ``providers``: the adapters there build on it, and
``discovery`` reads HTTP through it.
"""

from __future__ import annotations

from .http import (
    Answer,
    ApiClient,
    Fetched,
    HostCheck,
    Lookup,
    Resolve,
    SafeFetcher,
    WebhookPoster,
    host_addresses,
    host_addresses_now,
    is_public_address,
    is_receiver_address,
)
from .imap import (
    DEFAULT_PORTS as IMAP_PORTS,
)
from .imap import (
    FetchedMessage,
    ImapSession,
    RawFolder,
    SearchCriteria,
)
from .oauth import (
    App,
    Endpoints,
    OAuthClient,
    Profile,
    RefreshingTokens,
    Tokens,
    authorize_url,
    new_pkce,
)
from .pop3 import (
    DEFAULT_PORTS as POP3_PORTS,
)
from .pop3 import Pop3Session
from .smtp import (
    DEFAULT_PORTS as SMTP_PORTS,
)
from .smtp import (
    SmtpLogin,
    SmtpSession,
)
from .transport import (
    Pick,
    Server,
)

__all__ = [
    "Answer",
    "ApiClient",
    "App",
    "Endpoints",
    "Fetched",
    "FetchedMessage",
    "HostCheck",
    "IMAP_PORTS",
    "ImapSession",
    "Lookup",
    "OAuthClient",
    "POP3_PORTS",
    "Pick",
    "Pop3Session",
    "Profile",
    "RawFolder",
    "RefreshingTokens",
    "Resolve",
    "SMTP_PORTS",
    "SafeFetcher",
    "SearchCriteria",
    "Server",
    "SmtpLogin",
    "SmtpSession",
    "Tokens",
    "WebhookPoster",
    "authorize_url",
    "host_addresses",
    "host_addresses_now",
    "is_public_address",
    "is_receiver_address",
    "new_pkce",
]
