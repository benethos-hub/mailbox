"""The wire, one library each: ``imap`` (IMAPClient), ``smtp`` (smtplib),
``http`` (httpx), ``oauth`` (OAuth 2.0 over ``http``), ``pop3``
(poplib), ``jmap`` (JMAP over ``http``). ``transport`` holds TLS, the
timeouts and the failures below every library. ``wire`` reads the JSON
a server sends into shapes, for the protocols here and the adapters.

Each module speaks its protocol and nothing else: no ids, no folders of the
API, no decisions. Library errors leave it as ``MailboxServiceError``. It
imports nothing of ``providers``: the adapters there build on it, and
``discovery`` reads HTTP through it.
"""

from __future__ import annotations

from . import jmap, wire
from .http import (
    Answer,
    Answered,
    ApiClient,
    Fetched,
    HostCheck,
    Lookup,
    Resolve,
    SafeFetcher,
    ServerClient,
    WebhookPoster,
    host_addresses,
    host_addresses_now,
    is_public_address,
    is_receiver_address,
    refused,
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
    DeviceCode,
    Endpoints,
    OAuthClient,
    Profile,
    RefreshingTokens,
    Tokens,
    Waiting,
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
    "Answered",
    "ApiClient",
    "App",
    "DeviceCode",
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
    "ServerClient",
    "SearchCriteria",
    "Server",
    "SmtpLogin",
    "SmtpSession",
    "Tokens",
    "Waiting",
    "WebhookPoster",
    "authorize_url",
    "host_addresses",
    "host_addresses_now",
    "is_public_address",
    "is_receiver_address",
    "jmap",
    "new_pkce",
    "refused",
    "wire",
]
