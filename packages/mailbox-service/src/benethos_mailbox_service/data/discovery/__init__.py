"""Autodiscovery sources (CONCEPT 5.8).

Each source is a module behind :class:`DiscoverySource`. The sources only
look up: which of their answers count as confirmed, how they are ranked and
merged is decided in ``domain/discovery/``. Helpers each wrap one library:
``dns`` (dnspython), ``suffix`` (publicsuffixlist), ``autoconfig``
(defusedxml). ``sources`` puts them together. HTTP goes through
``data/protocols/http``.
"""

from __future__ import annotations

from . import placeholders
from .base import DiscoverySource, Finding, Query
from .sources import default_sources, preset_hosts
from .suffix import registrable_domain

__all__ = [
    "DiscoverySource",
    "Finding",
    "Query",
    "default_sources",
    "placeholders",
    "preset_hosts",
    "registrable_domain",
]
