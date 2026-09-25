"""Name lookups for autodiscovery. The only module that imports ``dnspython``.

MX records need dnspython, the standard library cannot query them. Host
addresses come from the system resolver, the same one a connection uses.
"""

from __future__ import annotations

from typing import Any, Protocol

import dns.asyncresolver
import dns.exception
import dns.resolver

from ...errors import ProviderUnavailableError

TIMEOUT = 5.0


class MxResolver(Protocol):
    async def resolve(self, qname: str, rdtype: str, *, lifetime: float) -> Any: ...


async def mx_hosts(
    domain: str, resolver: MxResolver | None = None, timeout: float = TIMEOUT
) -> list[str]:
    """The mail exchangers of a domain, most preferred first. Empty when the
    domain has none or does not exist."""
    resolver = resolver or dns.asyncresolver.Resolver()
    try:
        answer = await resolver.resolve(domain, "MX", lifetime=timeout)
    except (dns.resolver.NXDOMAIN, dns.resolver.NoAnswer):
        return []
    except dns.exception.Timeout:
        raise ProviderUnavailableError("the DNS lookup timed out") from None
    except dns.exception.DNSException as exc:
        raise ProviderUnavailableError(f"the DNS lookup failed: {exc}") from None
    records = sorted(answer, key=lambda record: record.preference)
    hosts = [record.exchange.to_text(omit_final_dot=True).lower() for record in records]
    # A null MX (RFC 7505) says the domain takes no mail.
    return [host for host in hosts if host not in ("", ".")]
