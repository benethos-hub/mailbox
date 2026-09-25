"""ISP autoconfig: the configuration file a domain publishes about itself.

Asks ``autoconfig.{domain}`` first, then the domain's ``.well-known`` path,
both over HTTPS only. Never a parent domain, never ``autoconfig.{tld}``.
"""

from __future__ import annotations

from urllib.parse import quote

from ...errors import MailboxServiceError
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
        errors: list[MailboxServiceError] = []
        for url in urls:
            try:
                found = await autoconfig.fetch(
                    self._fetcher, url, query.domain, self.name
                )
            except MailboxServiceError as exc:
                errors.append(exc)
                continue
            if found is not None and found.candidates:
                return found
        if errors:
            raise errors[0]
        return Finding()
