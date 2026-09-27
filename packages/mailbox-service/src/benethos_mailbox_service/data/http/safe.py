"""HTTPS lookups at hosts built from what a user typed, e.g. for
autodiscovery.

The URLs are built from what a user typed, so every request is treated as a
possible request forgery (CONCEPT 5.8, rules 3, 6 and 8):

- HTTPS only, certificates verified, no proxy from the environment.
- Every host, redirects included, must resolve to public addresses only.
  The connection then goes to the address that was checked, with the host
  name kept for SNI and certificate verification, so a second DNS answer
  cannot slip in a private address.
- At most three redirects, a short timeout and a size limit.
"""

from __future__ import annotations

import ipaddress
import socket
from collections.abc import Awaitable, Callable, Iterable
from dataclasses import dataclass
from typing import Any

import anyio
import httpx

from ...errors import ProviderError, ProviderUnavailableError
from .base import new_client, parse_url, read_capped, unreachable

TIMEOUT = 5.0
MAX_BYTES = 256 * 1024
MAX_REDIRECTS = 3

Resolve = Callable[[str, int], Awaitable[list[str]]]
# The same, for code in a worker thread.
Lookup = Callable[[str, int], list[str]]
# The address a host resolves to, None when it does not resolve. Raises when
# the host may not be connected to (CONCEPT 5.8, rule 6). The signature of
# ``SafeFetcher.checked_address``, shared by accounts and discovery so both
# apply the same rule and the same allow-list.
HostCheck = Callable[[str, int], Awaitable[str | None]]


async def host_addresses(host: str, port: int) -> list[str]:
    """Every address a host resolves to. Empty when it does not resolve."""
    try:
        infos = await anyio.getaddrinfo(host, port, type=socket.SOCK_STREAM)
    except (socket.gaierror, UnicodeError):
        return []
    return _distinct(infos)


def host_addresses_now(host: str, port: int) -> list[str]:
    """``host_addresses`` for code in a worker thread, e.g. a mail protocol."""
    try:
        infos = socket.getaddrinfo(host, port, type=socket.SOCK_STREAM)
    except (socket.gaierror, UnicodeError):
        return []
    return _distinct(infos)


def _distinct(infos: list[Any]) -> list[str]:
    seen: dict[str, None] = {}
    for info in infos:
        seen[str(info[4][0])] = None
    return list(seen)


# The NAT64 prefix (RFC 6052) carries an IPv4 address in its last 32 bits.
# Python judges 6to4 and Teredo by theirs, not this one.
_NAT64 = ipaddress.ip_network("64:ff9b::/96")
# Every public IPv6 address is in here (RFC 4291 2.4). Outside it Python
# calls some ranges global that are not, e.g. ::/96 and fec0::/10.
_GLOBAL_UNICAST = ipaddress.ip_network("2000::/3")

IPAddress = ipaddress.IPv4Address | ipaddress.IPv6Address


def unwrapped(address: str) -> IPAddress:
    """The address, an IPv4 address carried in IPv6 as the IPv4 address
    it reaches: IPv4-mapped and NAT64."""
    ip = ipaddress.ip_address(address.split("%", 1)[0])
    if isinstance(ip, ipaddress.IPv6Address):
        if ip.ipv4_mapped is not None:
            return ip.ipv4_mapped
        if ip in _NAT64:
            return ipaddress.IPv4Address(int(ip) & 0xFFFFFFFF)
    return ip


def is_public_address(address: str) -> bool:
    """False for private, loopback, link-local, shared, reserved and multicast
    addresses, including IPv4 addresses wrapped in IPv6."""
    ip = unwrapped(address)
    if isinstance(ip, ipaddress.IPv6Address) and ip not in _GLOBAL_UNICAST:
        return False
    return ip.is_global and not ip.is_multicast


@dataclass(frozen=True)
class Fetched:
    # The host that answered, after redirects.
    host: str
    body: bytes


class SafeFetcher:
    def __init__(
        self,
        resolve: Resolve = host_addresses,
        internal_hosts: Iterable[str] = (),
        transport: httpx.AsyncBaseTransport | None = None,
        timeout: float = TIMEOUT,
        max_bytes: int = MAX_BYTES,
        lookup: Lookup = host_addresses_now,
    ) -> None:
        self._resolve = resolve
        self._lookup = lookup
        # Hosts an operator allows although they resolve to private addresses.
        self._internal = frozenset(h.lower().rstrip(".") for h in internal_hosts)
        self._transport = transport
        self._timeout = timeout
        self._max_bytes = max_bytes

    async def get(self, url: str) -> Fetched | None:
        """The body of a ``200`` answer. None when there is nothing to find:
        the host does not resolve, or the answer is not ``200``."""
        async with new_client(self._transport, self._timeout) as client:
            target = parse_url(url)
            for _ in range(MAX_REDIRECTS + 1):
                if target.scheme != "https":
                    raise ProviderError(f"refused to fetch {target}: HTTPS only")
                host = target.raw_host.decode("ascii").lower()
                address = await self.checked_address(host, target.port or 443)
                if address is None:
                    return None
                try:
                    response = await self._send(client, target, host, address)
                except httpx.HTTPError as exc:
                    raise unreachable(exc, host) from None
                if isinstance(response, str):
                    target = target.join(response)
                    continue
                if response is None:
                    return None
                return Fetched(host=host, body=response)
        raise ProviderError(f"refused to follow more than {MAX_REDIRECTS} redirects")

    async def checked_address(self, host: str, port: int) -> str | None:
        """The address to connect to, None when the host does not resolve.
        Refuses a host with any non-public address, unless it is allowed as
        internal."""
        return self._judged(host, await self._resolve(host, port))

    def connect_address(self, host: str, port: int) -> str:
        """``checked_address`` for a mail protocol, which connects from a
        worker thread, at every connection. A host that does not resolve
        raises as well."""
        address = self._judged(host, self._lookup(host, port))
        if address is None:
            raise ProviderUnavailableError(f"{host} does not resolve")
        return address

    def _judged(self, host: str, addresses: list[str]) -> str | None:
        if not addresses:
            return None
        if host.lower().rstrip(".") not in self._internal:
            private = [a for a in addresses if not is_public_address(a)]
            if private:
                raise ProviderError(
                    f"refused to connect to {host}: it resolves to a non-public address"
                )
        return addresses[0]

    async def _send(
        self, client: httpx.AsyncClient, target: httpx.URL, host: str, address: str
    ) -> bytes | str | None:
        """The body, the next location of a redirect, or None."""
        pinned = target.copy_with(host=address)
        request = client.build_request(
            "GET",
            pinned,
            headers={"Host": target.netloc.decode("ascii")},
            extensions={"sni_hostname": host},
        )
        response = await client.send(request, stream=True)
        try:
            if response.is_redirect:
                return response.headers.get("location") or None
            if response.status_code != 200:
                return None
            return await read_capped(response, host, self._max_bytes)
        finally:
            await response.aclose()
