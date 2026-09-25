"""What both HTTP wrappers share: the client as this service configures
it, a body read up to a limit, and a failure to reach a host as this
project's error."""

from __future__ import annotations

import httpx

from ...errors import ProviderError, ProviderUnavailableError


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


def unreachable(exc: httpx.HTTPError, host: str) -> ProviderUnavailableError:
    """The failure named by its kind alone, never by the request: a URL
    may carry a token."""
    if isinstance(exc, httpx.TimeoutException):
        return ProviderUnavailableError(f"{host} did not answer in time")
    return ProviderUnavailableError(f"{host} is not reachable: {type(exc).__name__}")
