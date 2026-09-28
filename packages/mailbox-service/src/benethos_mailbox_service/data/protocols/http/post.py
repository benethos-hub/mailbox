"""Posts to the URL of a webhook (CONCEPT 6.5).

A webhook is registered on purpose, so its host may be in the local
network, e.g. an automation server. Still refused are addresses no
receiver has: link-local ones, among them the metadata service of most
cloud hosts, the metadata services outside link-local that we know of,
multicast and unspecified addresses. The connection goes to the
address that was checked, with the host name kept for SNI and the
certificate, so a second DNS answer cannot slip in another one. Redirects
are not followed, and the answer's body is not read.
"""

from __future__ import annotations

import ipaddress
from collections.abc import Mapping

import httpx

from ....errors import ProviderError, ProviderUnavailableError
from .base import new_client, parse_url, pinned_request, unreachable
from .safe import Resolve, host_addresses, unwrapped

TIMEOUT = 10.0

# Metadata services of cloud hosts outside the link-local range, which the
# ranges below do not catch: AWS over IPv6 in a private range, Alibaba
# Cloud in the shared address space of 100.64.0.0/10. Those ranges stay
# open, since a VPN such as Tailscale puts receivers there.
METADATA = frozenset(
    ipaddress.ip_address(a) for a in ("fd00:ec2::254", "100.100.100.200")
)


def is_receiver_address(address: str) -> bool:
    """False for link-local, multicast, unspecified and reserved addresses,
    including IPv4 addresses wrapped in IPv6, and for the metadata services
    in METADATA. Private and loopback pass."""
    ip = unwrapped(address)
    if ip in METADATA:
        return False
    return not (ip.is_link_local or ip.is_multicast or ip.is_unspecified) and not (
        ip.is_reserved and not ip.is_private
    )


class WebhookPoster:
    def __init__(
        self,
        resolve: Resolve = host_addresses,
        transport: httpx.AsyncBaseTransport | None = None,
        timeout: float = TIMEOUT,
    ) -> None:
        self._resolve = resolve
        self._transport = transport
        self._timeout = timeout

    async def post(self, url: str, body: bytes, headers: Mapping[str, str]) -> int:
        """The status the receiver answered. Raises when it cannot be
        reached or may not be posted to."""
        target = parse_url(url)
        if target.scheme not in ("http", "https") or not target.raw_host:
            raise ProviderError("a webhook url must be http or https, with a host")
        host = target.raw_host.decode("ascii").lower()
        port = target.port or (443 if target.scheme == "https" else 80)
        addresses = await self._resolve(host, port)
        if not addresses:
            raise ProviderUnavailableError(f"{host} does not resolve")
        refused = [a for a in addresses if not is_receiver_address(a)]
        if refused:
            raise ProviderError(f"refused to post to {host}: not an address to post to")
        async with new_client(self._transport, self._timeout) as client:
            request = pinned_request(
                client,
                "POST",
                target,
                host,
                addresses[0],
                headers=headers,
                content=body,
            )
            try:
                response = await client.send(request, stream=True)
            except httpx.HTTPError as exc:
                raise unreachable(exc, host) from None
            await response.aclose()
            return response.status_code
