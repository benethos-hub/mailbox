"""Autodiscovery sources (CONCEPT 5.8).

Each source is a module behind :class:`DiscoverySource`. The sources only
look up: which of their answers count as confirmed, how they are ranked and
merged is decided in ``domain/discovery.py``. Helpers each wrap one library:
``dns`` (dnspython), ``suffix`` (publicsuffixlist), ``autoconfig``
(defusedxml). HTTP goes through ``data/http``.
"""

from __future__ import annotations

from ..http import SafeFetcher
from . import placeholders
from .base import DiscoverySource, Finding, Query
from .isp import IspAutoconfigSource
from .ispdb import IspdbSource
from .mx import MxSource
from .presets import PresetSource, bundled
from .suffix import registrable_domain


def default_sources(fetcher: SafeFetcher, *, ispdb: bool) -> list[DiscoverySource]:
    """Every source in the order of CONCEPT 5.8. ``ispdb=False`` leaves out
    ISPDB, also behind MX."""
    presets = bundled()
    database = IspdbSource(fetcher) if ispdb else None
    sources: list[DiscoverySource] = [
        PresetSource(presets),
        IspAutoconfigSource(fetcher),
    ]
    if database is not None:
        sources.append(database)
    sources.append(MxSource(presets, database))
    return sources


def preset_hosts() -> frozenset[str]:
    """The server hosts our presets name, trusted wherever they turn up."""
    return bundled().server_hosts()


__all__ = [
    "DiscoverySource",
    "Finding",
    "Query",
    "SafeFetcher",
    "default_sources",
    "placeholders",
    "preset_hosts",
    "registrable_domain",
]
