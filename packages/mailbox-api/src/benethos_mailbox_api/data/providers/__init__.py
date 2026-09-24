"""Provider adapters and their registry.

One directory per provider, named like its registry key. Inside it:
``provider.py`` (the adapter), ``mappers.py`` where a foreign format is
translated (pure functions, testable offline), and a narrow export in
``__init__.py``. Everything outside ``data/providers/`` reaches an adapter
through :func:`build_provider`, never by importing a provider module.
"""

from __future__ import annotations

from collections.abc import Awaitable, Callable, Mapping

from ...errors import NotSupportedError
from ..models import ProviderType, Security, ServerProtocol
from .base import Capability, CredentialReader, MailProvider
from .imap import ImapProvider
from .imap import probe as probe_imap
from .memory import MemoryProvider

ProviderSettings = Mapping[str, str | int | bool]
ProviderFactory = Callable[
    [ProviderType, ProviderSettings, CredentialReader], MailProvider
]
ServerProbe = Callable[[ServerProtocol, str, int, Security], Awaitable[frozenset[str]]]

_REGISTRY: dict[
    ProviderType, Callable[[ProviderSettings, CredentialReader], MailProvider]
] = {
    ProviderType.MEMORY: lambda _settings, _credentials: MemoryProvider(),
    ProviderType.IMAP: ImapProvider,
}


def build_provider(
    kind: ProviderType, settings: ProviderSettings, credentials: CredentialReader
) -> MailProvider:
    """A new adapter for one account."""
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
    "build_provider",
    "probe_server",
]
