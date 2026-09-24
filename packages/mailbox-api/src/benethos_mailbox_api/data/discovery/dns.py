"""Name lookups for autodiscovery. The only module that imports ``dnspython``.

MX records need dnspython, the standard library cannot query them. Host
addresses come from the system resolver, the same one a connection uses.
"""

from __future__ import annotations

import ipaddress
import socket
from typing import Any, Protocol

import anyio
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


async def host_addresses(host: str, port: int) -> list[str]:
    """Every address a host resolves to. Empty when it does not resolve."""
    try:
        infos = await anyio.getaddrinfo(host, port, type=socket.SOCK_STREAM)
    except (socket.gaierror, UnicodeError):
        return []
    seen: dict[str, None] = {}
    for info in infos:
        seen[str(info[4][0])] = None
    return list(seen)


def is_public_address(address: str) -> bool:
    """False for private, loopback, link-local, shared, reserved and multicast
    addresses, including IPv4 addresses wrapped in IPv6."""
    ip = ipaddress.ip_address(address.split("%", 1)[0])
    if isinstance(ip, ipaddress.IPv6Address) and ip.ipv4_mapped is not None:
        ip = ip.ipv4_mapped
    return ip.is_global and not ip.is_multicast
