"""The protocol every discovery source implements."""

from __future__ import annotations

from dataclasses import dataclass
from typing import Protocol

from ..models import Candidate, DiscoverySourceName, Hint


@dataclass(frozen=True)
class Query:
    email: str
    # The domain of the address, lower case, IDN in ASCII (punycode).
    domain: str


@dataclass(frozen=True)
class Finding:
    """What one source found. Whether it counts as confirmed is decided in
    the domain, from the source and ``answered_by``."""

    candidates: tuple[Candidate, ...] = ()
    # Notes about the address as a whole.
    hints: tuple[Hint, ...] = ()
    # The host whose answer this is, after redirects. None for our own data.
    answered_by: str | None = None


class DiscoverySource(Protocol):
    """Looks up one address. Returns an empty finding when it knows nothing,
    raises a ``MailboxApiError`` when the lookup itself failed. Sends no
    credential, ever."""

    name: DiscoverySourceName

    async def lookup(self, query: Query) -> Finding: ...
