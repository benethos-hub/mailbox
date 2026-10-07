"""Provider adapters and their registry.

One directory per provider, named like its registry key. Inside it:
``provider.py`` (the adapter), ``mappers.py`` where a foreign format is
translated (pure functions, testable offline), and a narrow export in
``__init__.py``. ``registry`` picks the adapter of an account. Everything
outside ``data/providers/`` reaches an adapter through
:func:`build_provider`, never by importing a provider module.
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
    Capability,
    ChangedMessage,
    CredentialReader,
    Deletes,
    Deltas,
    Drafts,
    FolderChanges,
    ProviderSettings,
    Reads,
    Sends,
    TokenSource,
    Watches,
    Writes,
    capabilities_of,
)
from .guard import Pace
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
    "ChangedMessage",
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
    "capabilities_of",
    "OAuthClient",
    "Pace",
    "Pick",
    "ProviderFactory",
    "ProviderSettings",
    "RefreshingTokens",
    "ServerProbe",
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
]
