"""What both HTTP wrappers share: the client as this service configures
it, a request pinned to a checked address, a body read up to a limit,
and a failure to reach a host as this project's error."""

from __future__ import annotations

from collections.abc import Mapping

import httpx

from ....errors import ProviderError, ProviderUnavailableError


def new_client(
    transport: httpx.AsyncBaseTransport | None, timeout: float
) -> httpx.AsyncClient:
    """Certificates verified, no proxy from the environment, redirects
    left to the caller."""
    return httpx.AsyncClient(
        transport=transport,
        timeout=timeout,
        follow_redirects=False,
        trust_env=False,
        verify=True,
    )


def pinned_request(
    client: httpx.AsyncClient,
    method: str,
    target: httpx.URL,
    host: str,
    address: str,
    *,
    headers: Mapping[str, str] | None = None,
    content: bytes | None = None,
) -> httpx.Request:
    """A request for ``target`` sent to ``address``, the address that was
    checked: the name is not resolved again. The Host header and SNI keep
    ``host``, so the certificate is checked against the name."""
    return client.build_request(
        method,
        target.copy_with(host=address),
        content=content,
        headers={**(headers or {}), "Host": target.netloc.decode("ascii")},
        extensions={"sni_hostname": host} if target.scheme == "https" else {},
    )


async def read_capped(response: httpx.Response, host: str, max_bytes: int) -> bytes:
    """The body, refused once it grows past ``max_bytes``."""
    body = bytearray()
    async for chunk in response.aiter_bytes():
        body += chunk
        if len(body) > max_bytes:
            raise ProviderError(
                f"the answer of {host} is larger than {max_bytes} bytes"
            )
    return bytes(body)


def parse_url(url: str) -> httpx.URL:
    """``url`` parsed, or a ProviderError: what a user or a provider gave us
    is data, and data that is no URL must not crash the request."""
    try:
        return httpx.URL(url)
    except httpx.InvalidURL as exc:
        raise ProviderError(f"not a URL: {exc}") from None


def wire_host(target: httpx.URL) -> str:
    """The host of ``target`` as it goes on the wire: ASCII, lower case."""
    return target.raw_host.decode("ascii").lower()


def unreachable(exc: httpx.HTTPError, host: str) -> ProviderUnavailableError:
    """The failure named by its kind alone, never by the request: a URL
    may carry a token."""
    if isinstance(exc, httpx.TimeoutException):
        return ProviderUnavailableError(f"{host} did not answer in time")
    return ProviderUnavailableError(f"{host} is not reachable: {type(exc).__name__}")
