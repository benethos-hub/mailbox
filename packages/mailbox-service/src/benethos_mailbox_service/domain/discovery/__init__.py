"""Autodiscovery: from an address to ranked ways of connecting it
(CONCEPT 5.8). The sources in ``data/discovery`` look up, ``service``
decides, ``candidates`` holds what it decides on.
"""

from __future__ import annotations

from .candidates import connectable, sign_ins
from .service import DiscoveryService

__all__ = [
    "DiscoveryService",
    "connectable",
    "sign_ins",
]
