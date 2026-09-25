"""Posts to the URL of a webhook (CONCEPT 6.5).

A webhook is registered on purpose, so its host may be in the local
network, e.g. an automation server. Still refused are addresses no
receiver has: link-local ones, among them the metadata service of cloud
hosts, multicast and unspecified addresses. The connection goes to the
address that was checked, with the host name kept for SNI and the
certificate, so a second DNS answer cannot slip in another one. Redirects
are not followed, and the answer's body is not read.
"""

from __future__ import annotations

import ipaddress
from collections.abc import Mapping

import httpx

from ...errors import ProviderError, ProviderUnavailableError
from .base import new_client, parse_url, unreachable
from .safe import Resolve, host_addresses

TIMEOUT = 10.0


def is_receiver_address(address: str) -> bool:
    """False for link-local, multicast, unspecified and reserved addresses,
    including IPv4 addresses wrapped in IPv6. Private and loopback pass."""
    ip = ipaddress.ip_address(address.split("%", 1)[0])
    if isinstance(ip, ipaddress.IPv6Address) and ip.ipv4_mapped is not None:
        ip = ip.ipv4_mapped
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
        pinned = target.copy_with(host=addresses[0])
        extensions = {"sni_hostname": host} if target.scheme == "https" else {}
        async with new_client(self._transport, self._timeout) as client:
            request = client.build_request(
                "POST",
                pinned,
                content=body,
                headers={**headers, "Host": target.netloc.decode("ascii")},
                extensions=extensions,
            )
            try:
                response = await client.send(request, stream=True)
            except httpx.HTTPError as exc:
                raise unreachable(exc, host) from None
            await response.aclose()
            return response.status_code
