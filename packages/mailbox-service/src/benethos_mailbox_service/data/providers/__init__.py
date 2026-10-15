"""Provider adapters and what they share.

``base`` holds the contract, ``rules`` what every adapter answers the
same way, ``connections`` how each kind of account is connected, and
``guard``, ``settings``, ``sender`` and ``mailserver`` what several
adapters build on. ``registry`` picks the adapter of an account.

One directory per provider, named like its registry key. Inside it:
``provider.py`` (the adapter), ``mappers.py`` where a foreign format is
translated (pure functions, testable offline), the rest one module per
subject, and a narrow export in ``__init__.py``. Everything outside
``data/providers/`` reaches an adapter through :func:`build_provider`,
never by importing a provider module.
"""

from __future__ import annotations

from ..protocols import (
    App,
    DeviceCode,
    Endpoints,
    OAuthClient,
    Pick,
    RefreshingTokens,
    Tokens,
    Waiting,
    authorize_url,
    new_pkce,
)
from .base import (
    PROTOCOLS,
    Capability,
    CredentialReader,
    Deletes,
    Deltas,
    Drafts,
    FolderChanges,
    ProviderSettings,
    Reads,
    Sends,
    Summaries,
    ThreadHeaders,
    ThreadMessages,
    Threads,
    TokenSource,
    Watches,
    Writes,
)
from .connections import CONNECTIONS, connection_of
from .guard import Pace, Timing
from .registry import (
    ProviderFactory,
    ServerProbe,
    build_provider,
    probe_server,
    project_client_id,
    settings_defaults,
    settings_from_servers,
    sign_in,
)
from .settings import hosts_in

__all__ = [
    "App",
    "Capability",
    "CredentialReader",
    "DeviceCode",
    "FolderChanges",
    "Endpoints",
    "Reads",
    "Deletes",
    "Deltas",
    "Drafts",
    "Sends",
    "Watches",
    "Writes",
    "PROTOCOLS",
    "OAuthClient",
    "Pace",
    "Timing",
    "Pick",
    "ProviderFactory",
    "ProviderSettings",
    "RefreshingTokens",
    "ServerProbe",
    "Summaries",
    "ThreadHeaders",
    "ThreadMessages",
    "Threads",
    "TokenSource",
    "Tokens",
    "Waiting",
    "authorize_url",
    "build_provider",
    "hosts_in",
    "new_pkce",
    "probe_server",
    "project_client_id",
    "settings_defaults",
    "settings_from_servers",
    "sign_in",
    "CONNECTIONS",
    "connection_of",
]
