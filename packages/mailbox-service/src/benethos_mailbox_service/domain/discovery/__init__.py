"""Autodiscovery: from an address to ranked ways of connecting it
(CONCEPT 5.8). The sources in ``data/discovery`` look up, ``service``
decides.
"""

from __future__ import annotations

from .service import DiscoveryService, connectable, sign_ins

__all__ = [
    "DiscoveryService",
    "connectable",
    "sign_ins",
]
