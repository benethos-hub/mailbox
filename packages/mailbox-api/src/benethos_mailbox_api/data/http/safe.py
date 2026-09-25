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

import anyio
import httpx

from ...errors import ProviderError
from .base import new_client, read_capped, unreachable

TIMEOUT = 5.0
MAX_BYTES = 256 * 1024
MAX_REDIRECTS = 3

Resolve = Callable[[str, int], Awaitable[list[str]]]
# The address a host resolves to, None when it does not resolve; raises when
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


@dataclass(frozen=True)
class Fetched:
    url: str
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
    ) -> None:
        self._resolve = resolve
        # Hosts an operator allows although they resolve to private addresses.
        self._internal = frozenset(h.lower().rstrip(".") for h in internal_hosts)
        self._transport = transport
        self._timeout = timeout
        self._max_bytes = max_bytes

    async def get(self, url: str) -> Fetched | None:
        """The body of a ``200`` answer. None when there is nothing to find:
        the host does not resolve, or the answer is not ``200``."""
        async with new_client(self._transport, self._timeout) as client:
            target = httpx.URL(url)
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
                if isinstance(response, httpx.URL):
                    target = target.join(response)
                    continue
                if response is None:
                    return None
                return Fetched(url=str(target), host=host, body=response)
        raise ProviderError(f"refused to follow more than {MAX_REDIRECTS} redirects")

    async def checked_address(self, host: str, port: int) -> str | None:
        """The address to connect to, None when the host does not resolve.
        Refuses a host with any non-public address, unless it is allowed as
        internal."""
        addresses = await self._resolve(host, port)
        if not addresses:
            return None
        if host not in self._internal:
            private = [a for a in addresses if not is_public_address(a)]
            if private:
                raise ProviderError(
                    f"refused to connect to {host}: it resolves to a non-public address"
                )
        return addresses[0]

    async def _send(
        self, client: httpx.AsyncClient, target: httpx.URL, host: str, address: str
    ) -> bytes | httpx.URL | None:
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
                location = response.headers.get("location")
                return httpx.URL(location) if location else None
            if response.status_code != 200:
                return None
            return await read_capped(response, host, self._max_bytes)
        finally:
            await response.aclose()
