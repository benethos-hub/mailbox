"""Provider adapters and their registry.

One directory per provider, named like its registry key. Inside it:
``provider.py`` (the adapter), ``mappers.py`` where a foreign format is
translated (pure functions, testable offline), and a narrow export in
``__init__.py``. Everything outside ``data/providers/`` reaches an adapter
through :func:`build_provider`, never by importing a provider module.
"""

from __future__ import annotations

from collections.abc import Callable, Mapping

from ...errors import NotSupportedError
from ..models import ProviderType
from .base import Capability, CredentialReader, MailProvider
from .imap import ImapProvider
from .memory import MemoryProvider

ProviderSettings = Mapping[str, str | int | bool]
ProviderFactory = Callable[
    [ProviderType, ProviderSettings, CredentialReader], MailProvider
]

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


__all__ = [
    "Capability",
    "CredentialReader",
    "MailProvider",
    "ProviderFactory",
    "ProviderSettings",
    "build_provider",
]
