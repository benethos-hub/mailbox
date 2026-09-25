"""ISP autoconfig: the configuration file a domain publishes about itself.

Asks ``autoconfig.{domain}`` first, then the domain's ``.well-known`` path,
both over HTTPS only. Never a parent domain, never ``autoconfig.{tld}``.
"""

from __future__ import annotations

from urllib.parse import quote

from ...errors import MailboxApiError
from ..http import SafeFetcher
from ..models import DiscoverySourceName
from . import autoconfig
from .base import Finding, Query


class IspAutoconfigSource:
    name = DiscoverySourceName.AUTOCONFIG

    def __init__(self, fetcher: SafeFetcher) -> None:
        self._fetcher = fetcher

    async def lookup(self, query: Query) -> Finding:
        urls = [
            f"https://autoconfig.{query.domain}/mail/config-v1.1.xml"
            f"?emailaddress={quote(query.email, safe='@')}",
            f"https://{query.domain}/.well-known/autoconfig/mail/config-v1.1.xml",
        ]
        errors: list[MailboxApiError] = []
        for url in urls:
            try:
                fetched = await self._fetcher.get(url)
                if fetched is None:
                    continue
                candidates = autoconfig.parse(fetched.body, query.domain, self.name)
            except MailboxApiError as exc:
                errors.append(exc)
                continue
            if candidates:
                return Finding(candidates=tuple(candidates), answered_by=fetched.host)
        if errors:
            raise errors[0]
        return Finding()
