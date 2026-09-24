"""The one place that talks to the Mailbox API."""

from __future__ import annotations

import os
from typing import Any

import httpx

from .errors import ApiError, ServiceUnavailableError

DEFAULT_URL = "http://127.0.0.1:8080"
URL_ENV = "MAILBOX_API_URL"
TOKEN_ENV = "MAILBOX_API_TOKEN"


class MailboxApiClient:
    def __init__(
        self,
        base_url: str | None = None,
        token: str | None = None,
        transport: httpx.AsyncBaseTransport | None = None,
    ) -> None:
        self.base_url = (base_url or os.environ.get(URL_ENV) or DEFAULT_URL).rstrip("/")
        token = token if token is not None else os.environ.get(TOKEN_ENV, "")
        self._http = httpx.AsyncClient(
            base_url=self.base_url,
            headers={"Authorization": f"Bearer {token}"} if token else {},
            timeout=httpx.Timeout(30.0, connect=5.0),
            transport=transport,
        )

    async def request(self, method: str, path: str, **kwargs: Any) -> Any:
        try:
            response = await self._http.request(method, path, **kwargs)
        except httpx.TransportError:
            raise ServiceUnavailableError(
                f"The Mailbox API service is not reachable at {self.base_url}. "
                "Start it with `benethos-mailbox-api serve`."
            ) from None
        if response.is_error:
            raise _api_error(response)
        if response.status_code == 204:
            return None
        return response.json()

    async def me(self) -> dict[str, Any]:
        """The caller: its accounts, each with the operations allowed on it."""
        result: dict[str, Any] = await self.request("GET", "/v1/me")
        return result

    async def list_accounts(self) -> list[dict[str, Any]]:
        result: list[dict[str, Any]] = await self.request("GET", "/v1/accounts")
        return result

    async def list_folders(self, account_id: str) -> list[dict[str, Any]]:
        result: list[dict[str, Any]] = await self.request(
            "GET", f"/v1/accounts/{account_id}/folders"
        )
        return result

    async def list_messages(
        self, account_id: str | None, params: dict[str, Any]
    ) -> dict[str, Any]:
        """One account's messages, or with ``account_id`` None, those of
        every account the caller may read."""
        path = f"/v1/accounts/{account_id}/messages" if account_id else "/v1/messages"
        wanted = {k: v for k, v in params.items() if v is not None}
        result: dict[str, Any] = await self.request("GET", path, params=wanted)
        return result

    async def get_message(self, account_id: str, message_id: str) -> dict[str, Any]:
        result: dict[str, Any] = await self.request(
            "GET", f"/v1/accounts/{account_id}/messages/{message_id}"
        )
        return result

    async def aclose(self) -> None:
        await self._http.aclose()


def _api_error(response: httpx.Response) -> ApiError:
    try:
        error = response.json()["error"]
        return ApiError(response.status_code, error["code"], error["message"])
    except (ValueError, KeyError, TypeError):
        return ApiError(
            response.status_code, "unexpected_response", response.reason_phrase
        )
