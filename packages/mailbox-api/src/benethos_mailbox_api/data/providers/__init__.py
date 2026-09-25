"""Provider adapters and their registry.

One directory per provider, named like its registry key. Inside it:
``provider.py`` (the adapter), ``mappers.py`` where a foreign format is
translated (pure functions, testable offline), and a narrow export in
``__init__.py``. Everything outside ``data/providers/`` reaches an adapter
through :func:`build_provider`, never by importing a provider module.
"""

from __future__ import annotations

from collections.abc import Awaitable, Callable
from typing import Protocol

from ...errors import NotSupportedError
from ..models import CredentialKind, MailServer, ProviderType, Security, ServerProtocol
from .base import (
    Capability,
    CredentialReader,
    MailProvider,
    ProviderSettings,
    TokenSource,
)
from .imap import ImapProvider
from .imap import probe as probe_imap
from .imap import settings_from as imap_settings
from .memory import MemoryProvider
from .microsoft import MicrosoftProvider
from .microsoft import endpoints as microsoft_endpoints
from .protocols.oauth import (
    App,
    Endpoints,
    OAuthClient,
    RefreshingTokens,
    Tokens,
    authorize_url,
    new_pkce,
)
from .ratelimit import backoff
from .rules import hosts_in


class ProviderFactory(Protocol):
    """Makes the adapter of one account. ``tokens`` only for a provider that
    signs in with OAuth."""

    def __call__(
        self,
        kind: ProviderType,
        settings: ProviderSettings,
        credentials: CredentialReader,
        /,
        *,
        tokens: TokenSource | None = None,
    ) -> MailProvider: ...


ServerProbe = Callable[[ServerProtocol, str, int, Security], Awaitable[frozenset[str]]]

_REGISTRY: dict[
    ProviderType, Callable[[ProviderSettings, CredentialReader], MailProvider]
] = {
    ProviderType.MEMORY: lambda _settings, _credentials: MemoryProvider(),
    ProviderType.IMAP: ImapProvider,
}
# Providers that sign in with OAuth: they get a token source instead.
_SIGNED_IN: dict[
    ProviderType, Callable[[ProviderSettings, TokenSource], MailProvider]
] = {
    ProviderType.MICROSOFT: lambda _settings, tokens: MicrosoftProvider(tokens),
}


# How the accounts of a provider that signs in with OAuth do so, given the
# deployment's tenant or its like.
_SIGN_IN: dict[ProviderType, Callable[[str | None], Endpoints]] = {
    ProviderType.MICROSOFT: microsoft_endpoints,
}


# What an adapter assumes where the settings say nothing, given the
# account's address: IMAP logs in with the address unless told otherwise.
_DEFAULTS: dict[ProviderType, Callable[[str], dict[str, str | int | bool]]] = {
    ProviderType.IMAP: lambda email: {"username": email},
}


def settings_defaults(kind: ProviderType, email: str) -> dict[str, str | int | bool]:
    """The settings of ``kind`` that follow from the address alone."""
    make = _DEFAULTS.get(kind)
    return make(email) if make is not None else {}


# The settings of an account of a provider from the servers autodiscovery
# found, as the adapter reads them.
_FROM_SERVERS: dict[
    ProviderType,
    Callable[[list[MailServer], CredentialKind, str], dict[str, str | int | bool]],
] = {
    ProviderType.IMAP: imap_settings,
}


def settings_from_servers(
    kind: ProviderType,
    servers: list[MailServer],
    credential: CredentialKind,
    email: str,
) -> dict[str, str | int | bool]:
    """The settings for ``POST /v1/accounts`` from discovered servers. Empty
    for a provider that needs none, or none of these."""
    make = _FROM_SERVERS.get(kind)
    return make(servers, credential, email) if make is not None else {}


def sign_in(kind: ProviderType, tenant: str | None = None) -> Endpoints:
    """Where accounts of ``kind`` sign in, and what the adapter asks for."""
    try:
        return _SIGN_IN[kind](tenant)
    except KeyError:
        raise NotSupportedError(f"{kind} accounts do not sign in with OAuth") from None


def build_provider(
    kind: ProviderType,
    settings: ProviderSettings,
    credentials: CredentialReader,
    /,
    *,
    tokens: TokenSource | None = None,
) -> MailProvider:
    """A new adapter for one account."""
    if kind in _SIGNED_IN:
        if tokens is None:
            raise NotSupportedError(
                f"no OAuth app for {kind} is set up in this deployment"
            )
        return _SIGNED_IN[kind](settings, tokens)
    try:
        factory = _REGISTRY[kind]
    except KeyError:
        raise NotSupportedError(f"provider {kind} is not implemented yet") from None
    return factory(settings, credentials)


async def probe_server(
    protocol: ServerProtocol, host: str, port: int, security: Security
) -> frozenset[str]:
    """What a mail server announces before any login, e.g. ``IDLE`` or
    ``AUTH=XOAUTH2``. Connects anonymously and sends no credential."""
    if protocol is not ServerProtocol.IMAP:
        raise NotSupportedError(f"cannot probe {protocol} servers yet")
    return await probe_imap(host, port, str(security))


__all__ = [
    "App",
    "Capability",
    "CredentialReader",
    "Endpoints",
    "MailProvider",
    "OAuthClient",
    "ProviderFactory",
    "ProviderSettings",
    "RefreshingTokens",
    "ServerProbe",
    "TokenSource",
    "Tokens",
    "authorize_url",
    "backoff",
    "build_provider",
    "hosts_in",
    "new_pkce",
    "probe_server",
    "settings_defaults",
    "settings_from_servers",
    "sign_in",
]
