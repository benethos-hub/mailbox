"""Provider adapters and their registry.

One directory per provider, named like its registry key. Inside it:
``provider.py`` (the adapter), ``mappers.py`` where a foreign format is
translated (pure functions, testable offline), and a narrow export in
``__init__.py``. Everything outside ``data/providers/`` reaches an adapter
through :func:`build_provider`, never by importing a provider module.
"""

from __future__ import annotations

from collections.abc import Awaitable, Callable, Mapping
from typing import Protocol

from ...errors import NotSupportedError
from ..models import ProviderType, Security, ServerProtocol
from .base import Capability, CredentialReader, MailProvider, TokenSource
from .imap import ImapProvider
from .imap import probe as probe_imap
from .memory import MemoryProvider
from .microsoft import MicrosoftProvider

ProviderSettings = Mapping[str, str | int | bool]


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
    "Capability",
    "CredentialReader",
    "MailProvider",
    "ProviderFactory",
    "ProviderSettings",
    "ServerProbe",
    "TokenSource",
    "build_provider",
    "probe_server",
]
