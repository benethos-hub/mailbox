"""Autodiscovery sources (CONCEPT 5.8).

Each source is a module behind :class:`DiscoverySource`. The sources only
look up: which of their answers count as confirmed, how they are ranked and
merged is decided in ``domain/discovery.py``. Helpers each wrap one library:
``fetch`` (httpx), ``dns`` (dnspython), ``suffix`` (publicsuffixlist),
``autoconfig`` (defusedxml).
"""

from __future__ import annotations

from .base import DiscoverySource, Finding, Query

__all__ = ["DiscoverySource", "Finding", "Query"]
