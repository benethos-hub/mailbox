"""The sources of autodiscovery together, in the order of CONCEPT 5.8, and
the hosts our presets name."""

from __future__ import annotations

from ..protocols import SafeFetcher
from .base import DiscoverySource
from .isp import IspAutoconfigSource
from .ispdb import IspdbSource
from .mx import MxSource
from .presets import PresetSource, bundled


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
