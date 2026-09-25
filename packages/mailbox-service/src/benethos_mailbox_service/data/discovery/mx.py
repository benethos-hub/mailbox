"""MX lookup: who receives the domain's mail.

For a custom domain hosted elsewhere, the MX host names the provider: its
registrable domain is looked up in the presets, then in ISPDB. DNS without
DNSSEC can be forged, so these answers are never confirmed on their own.
"""

from __future__ import annotations

from collections.abc import Awaitable, Callable

from ..models import DiscoverySourceName
from .base import Finding, Query
from .dns import mx_hosts
from .ispdb import IspdbSource
from .presets import Presets, bundled
from .suffix import registrable_domain

MxLookup = Callable[[str], Awaitable[list[str]]]


class MxSource:
    name = DiscoverySourceName.MX

    def __init__(
        self,
        presets: Presets | None = None,
        ispdb: IspdbSource | None = None,
        lookup_mx: MxLookup = mx_hosts,
    ) -> None:
        self._presets = presets or bundled()
        # None when ISPDB is switched off.
        self._ispdb = ispdb
        self._lookup_mx = lookup_mx

    async def lookup(self, query: Query) -> Finding:
        own = registrable_domain(query.domain)
        for host in await self._lookup_mx(query.domain):
            base = registrable_domain(host)
            # The domain receives its own mail: MX says nothing new.
            if base is None or base == own:
                continue
            preset = self._presets.by_mx_domain(base)
            if preset is not None:
                found = preset.finding(self.name)
            elif self._ispdb is not None:
                found = await self._ispdb.for_domain(base, self.name)
            else:
                continue
            if found.candidates or found.hints:
                return Finding(
                    candidates=found.candidates, hints=found.hints, answered_by=host
                )
        return Finding()
