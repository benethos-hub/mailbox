"""HTTP, the one home of ``httpx``.

``safe`` fetches from hosts built from what a user typed, guarded against
request forgery. ``api`` talks JSON to the known hosts of a provider, such
as an OAuth token endpoint. ``post`` posts events to webhook receivers.
``server`` talks JSON to a mail server an account names, such as a JMAP
server.
"""

from __future__ import annotations

from .api import Answer, ApiClient, refused
from .post import WebhookPoster, is_receiver_address
from .safe import (
    Answered,
    HostCheck,
    Lookup,
    Resolve,
    SafeFetcher,
    host_addresses,
    host_addresses_now,
    is_public_address,
)
from .server import ServerClient

__all__ = [
    "Answer",
    "Answered",
    "ApiClient",
    "HostCheck",
    "Lookup",
    "Resolve",
    "SafeFetcher",
    "ServerClient",
    "WebhookPoster",
    "host_addresses",
    "host_addresses_now",
    "is_receiver_address",
    "is_public_address",
    "refused",
]
