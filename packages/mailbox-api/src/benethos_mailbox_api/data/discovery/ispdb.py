"""ISPDB: Thunderbird's shared database of provider settings.

A lookup tells Mozilla which domain is being set up, so this source can be
switched off (CONCEPT 5.8, rule 9).
"""

from __future__ import annotations

from ..models import DiscoverySourceName
from . import autoconfig
from .base import Finding, Query
from .fetch import SafeFetcher

ISPDB_URL = "https://autoconfig.thunderbird.net/v1.1/"


class IspdbSource:
    name = DiscoverySourceName.ISPDB

    def __init__(self, fetcher: SafeFetcher, base_url: str = ISPDB_URL) -> None:
        self._fetcher = fetcher
        self._base_url = base_url

    async def lookup(self, query: Query) -> Finding:
        return await self.for_domain(query.domain, self.name)

    async def for_domain(self, domain: str, source: DiscoverySourceName) -> Finding:
        """The entry of one domain, marked as coming from ``source``."""
        fetched = await self._fetcher.get(self._base_url + domain)
        if fetched is None:
            return Finding()
        candidates = autoconfig.parse(fetched.body, domain, source)
        return Finding(candidates=tuple(candidates), answered_by=fetched.host)
