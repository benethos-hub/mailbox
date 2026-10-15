"""How each kind of account is connected, as its adapter describes it
(docs/UNIFORM.md, U6): the UI draws its forms from these."""

from __future__ import annotations

from ...data.models import Connection, ProviderType
from ...data.providers import CONNECTIONS


def connection_of(kind: ProviderType | str) -> Connection:
    """The description of one kind of account."""
    return CONNECTIONS[ProviderType(kind)]


def connections() -> list[Connection]:
    """Every kind of account but the memory one, in the order of
    ``ProviderType``."""
    return [c for k, c in CONNECTIONS.items() if k is not ProviderType.MEMORY]
