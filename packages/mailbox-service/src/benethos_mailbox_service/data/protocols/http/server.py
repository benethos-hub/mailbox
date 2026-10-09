"""JSON over HTTPS to a mail server an account names, e.g. a JMAP server.

The host comes from what a user typed, so every request goes to the
address ``pick`` checked for it, with the host name kept for SNI and the
certificate, as a mail protocol connects. Certificates are checked against
the CAs of the system, which ``SSL_CERT_FILE`` can name, as for IMAP.
HTTPS only, no proxy from the environment, redirects left to the caller,
a timeout and a size limit.

A server-sent event stream is read line by line, each line up to a limit.
"""

from __future__ import annotations

import ssl
from collections.abc import AsyncIterator, Mapping
from contextlib import asynccontextmanager
from typing import Any

import anyio
import httpx

from benethos_mailbox_common.canonical import compact

from ....errors import ProviderError
from ..transport import Pick
from .api import MAX_BYTES, TIMEOUT, Answer
from .base import parse_url, pinned_request, read_capped, unreachable, wire_host

# A line of an event stream: one event's data is a small JSON object.
MAX_LINE = 64 * 1024


def _client(transport: httpx.AsyncBaseTransport | None) -> httpx.AsyncClient:
    return httpx.AsyncClient(
        transport=transport,
        follow_redirects=False,
        trust_env=False,
        # The CAs of the system, as ssl.create_default_context reads them,
        # SSL_CERT_FILE included.
        verify=ssl.create_default_context(),
    )


class ServerClient:
    def __init__(
        self,
        pick: Pick | None = None,
        transport: httpx.AsyncBaseTransport | None = None,
        timeout: float = TIMEOUT,
        max_bytes: int = MAX_BYTES,
    ) -> None:
        """``pick`` checks the host of each request. Without it the name is
        connected to as it is."""
        self._pick = pick
        self._client = _client(transport)
        self._timeout = timeout
        self._max_bytes = max_bytes

    async def request(
        self,
        method: str,
        url: str,
        *,
        headers: Mapping[str, str] | None = None,
        json_body: Any = None,
        content: bytes | None = None,
    ) -> Answer:
        """Any answer, whatever its status, goes back to the caller."""
        request, host = await self._request(
            method, url, headers=headers, json_body=json_body, content=content
        )
        try:
            response = await self._client.send(request, stream=True)
            try:
                body = await read_capped(response, host, self._max_bytes)
            finally:
                await response.aclose()
        except httpx.HTTPError as exc:
            raise unreachable(exc, host) from None
        return Answer(response.status_code, body, dict(response.headers))

    @asynccontextmanager
    async def lines(
        self, url: str, *, headers: Mapping[str, str] | None = None, wait: float
    ) -> AsyncIterator[tuple[Answer, AsyncIterator[str]]]:
        """A stream of lines, e.g. server-sent events. The answer's status
        and headers, and its lines while it is open. A stream that answers
        anything but 200 has its body read up to the limit instead.
        ``wait``: how long a read may wait for the next line."""
        request, host = await self._request("GET", url, headers=headers)
        request.extensions["timeout"] = httpx.Timeout(
            self._timeout, read=wait
        ).as_dict()
        try:
            response = await self._client.send(request, stream=True)
        except httpx.HTTPError as exc:
            raise unreachable(exc, host) from None
        try:
            if response.status_code != 200:
                body = await read_capped(response, host, self._max_bytes)
                yield (
                    Answer(response.status_code, body, dict(response.headers)),
                    _no_lines(),
                )
                return
            answer = Answer(response.status_code, b"", dict(response.headers))
            yield answer, _lines(response, host)
        except httpx.HTTPError as exc:
            raise unreachable(exc, host) from None
        finally:
            with anyio.CancelScope(shield=True):
                await response.aclose()

    async def close(self) -> None:
        await self._client.aclose()

    async def _request(
        self,
        method: str,
        url: str,
        *,
        headers: Mapping[str, str] | None = None,
        json_body: Any = None,
        content: bytes | None = None,
    ) -> tuple[httpx.Request, str]:
        target = parse_url(url)
        if target.scheme != "https" or not target.raw_host:
            raise ProviderError("refused to call a server without HTTPS")
        host = wire_host(target)
        port = target.port or 443
        address = (
            await anyio.to_thread.run_sync(self._pick, host, port)
            if self._pick is not None
            else host
        )
        if json_body is not None:
            content = compact(json_body).encode()
            headers = {**(headers or {}), "Content-Type": "application/json"}
        request = pinned_request(
            self._client,
            method,
            target,
            host,
            address,
            headers=headers,
            content=content,
        )
        request.extensions["timeout"] = httpx.Timeout(self._timeout).as_dict()
        return request, host


async def _lines(response: httpx.Response, host: str) -> AsyncIterator[str]:
    """The lines of a stream, refused once one grows past ``MAX_LINE``."""
    pending = ""
    async for text in response.aiter_text():
        pending += text
        *done, pending = pending.split("\n")
        for line in done:
            yield line.removesuffix("\r")
        if len(pending) > MAX_LINE:
            raise ProviderError(f"{host} sent a line longer than {MAX_LINE} bytes")


async def _no_lines() -> AsyncIterator[str]:
    return
    yield  # pragma: no cover
