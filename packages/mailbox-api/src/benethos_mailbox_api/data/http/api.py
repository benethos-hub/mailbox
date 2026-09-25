"""JSON over HTTPS to the known hosts of a provider: an OAuth token
endpoint, a mail API such as Microsoft Graph.

The hosts come from this code or the operator's settings, never from what
a user typed, so the forgery guards of ``safe`` are not needed here. Still:
HTTPS only, certificates verified, no proxy from the environment, a
timeout and a size limit. Failures to reach the host become
``ProviderUnavailableError``; any answer, whatever its status, goes back to
the caller, which knows what the provider means by it.
"""

from __future__ import annotations

import json
from collections.abc import Mapping
from dataclasses import dataclass, field
from typing import Any

import httpx

from ...errors import ProviderError
from .base import new_client, read_capped, unreachable

TIMEOUT = 30.0
# Enough for a message with its attachments (25 MB) in base64.
MAX_BYTES = 40 * 1024 * 1024


@dataclass(frozen=True)
class Answer:
    status: int
    body: bytes
    headers: Mapping[str, str] = field(default_factory=dict)

    @property
    def ok(self) -> bool:
        return 200 <= self.status < 300

    def json(self) -> Any:
        """The body as JSON; ``ProviderError`` when it is none."""
        try:
            return json.loads(self.body) if self.body else None
        except ValueError:
            raise ProviderError("the provider answered with no valid JSON") from None


class ApiClient:
    def __init__(
        self,
        transport: httpx.AsyncBaseTransport | None = None,
        timeout: float = TIMEOUT,
        max_bytes: int = MAX_BYTES,
    ) -> None:
        self._client = new_client(transport, timeout)
        self._max_bytes = max_bytes

    async def request(
        self,
        method: str,
        url: str,
        *,
        headers: Mapping[str, str] | None = None,
        params: Mapping[str, str] | None = None,
        form: Mapping[str, str] | None = None,
        json_body: Any = None,
        content: bytes | None = None,
    ) -> Answer:
        target = httpx.URL(url)
        if target.scheme != "https":
            raise ProviderError(f"refused to call {target.host}: HTTPS only")
        request = self._client.build_request(
            method,
            target,
            headers=dict(headers or {}),
            params=dict(params) if params else None,
            data=dict(form) if form is not None else None,
            json=json_body,
            content=content,
        )
        try:
            response = await self._client.send(request, stream=True)
            try:
                body = await read_capped(response, target.host, self._max_bytes)
            finally:
                await response.aclose()
        except httpx.HTTPError as exc:
            raise unreachable(exc, target.host) from None
        return Answer(response.status_code, body, dict(response.headers))

    async def close(self) -> None:
        await self._client.aclose()
