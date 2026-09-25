"""HTTP, the one home of ``httpx``.

``safe`` fetches from hosts built from what a user typed, guarded against
request forgery; ``api`` talks JSON to the known hosts of a provider, such
as an OAuth token endpoint.
"""

from __future__ import annotations

from .api import Answer, ApiClient
from .safe import Fetched, SafeFetcher, host_addresses, is_public_address

__all__ = [
    "Answer",
    "ApiClient",
    "Fetched",
    "SafeFetcher",
    "host_addresses",
    "is_public_address",
]
