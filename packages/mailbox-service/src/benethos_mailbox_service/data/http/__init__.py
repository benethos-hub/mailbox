"""HTTP, the one home of ``httpx``.

``safe`` fetches from hosts built from what a user typed, guarded against
request forgery. ``api`` talks JSON to the known hosts of a provider, such
as an OAuth token endpoint. ``post`` posts events to webhook receivers.
"""

from __future__ import annotations

from .api import Answer, ApiClient
from .post import WebhookPoster, is_receiver_address
from .safe import (
    Fetched,
    HostCheck,
    Resolve,
    SafeFetcher,
    host_addresses,
    is_public_address,
)

__all__ = [
    "Answer",
    "ApiClient",
    "Fetched",
    "HostCheck",
    "Resolve",
    "SafeFetcher",
    "WebhookPoster",
    "host_addresses",
    "is_receiver_address",
    "is_public_address",
]
