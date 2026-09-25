from __future__ import annotations

from collections.abc import Callable

import httpx
import pytest

from benethos_mailbox_mcp.client import DEFAULT_URL, MailboxApiClient
from benethos_mailbox_mcp.errors import ApiError, ServiceUnavailableError

ACCOUNT = {"id": "acc_1", "provider": "imap", "email": "me@example.com"}


async def test_sends_bearer_and_parses(make_client: Callable) -> None:
    seen: list[httpx.Request] = []

    def handler(request: httpx.Request) -> httpx.Response:
        seen.append(request)
        return httpx.Response(200, json=[ACCOUNT])

    client = make_client(handler)
    assert await client.list_accounts() == [ACCOUNT]
    assert seen[0].headers["authorization"] == "Bearer secret"
    assert seen[0].url == "http://mail.test/v1/accounts"
    await client.aclose()


async def test_error_envelope_becomes_api_error(make_client: Callable) -> None:
    client = make_client(
        lambda _: httpx.Response(
            404, json={"error": {"code": "not_found", "message": "gone"}}
        )
    )
    with pytest.raises(ApiError, match=r"gone \(not_found, HTTP 404\)"):
        await client.request("GET", "/v1/accounts/x")
    await client.aclose()


async def test_unexpected_error_body(make_client: Callable) -> None:
    client = make_client(lambda _: httpx.Response(500, text="boom"))
    with pytest.raises(ApiError) as exc:
        await client.request("GET", "/v1/accounts")
    assert exc.value.code == "unexpected_response"
    await client.aclose()


async def test_no_content(make_client: Callable) -> None:
    client = make_client(lambda _: httpx.Response(204))
    assert await client.request("DELETE", "/v1/accounts/x") is None
    await client.aclose()


async def test_unreachable_service_says_what_to_do(make_client: Callable) -> None:
    def handler(request: httpx.Request) -> httpx.Response:
        raise httpx.ConnectError("refused", request=request)

    client = make_client(handler)
    with pytest.raises(ServiceUnavailableError, match="benethos-mailbox-api serve"):
        await client.list_accounts()
    await client.aclose()


async def test_url_and_token_from_environment(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    monkeypatch.setenv("MAILBOX_API_URL", "http://elsewhere:9/")
    monkeypatch.setenv("MAILBOX_API_TOKEN", "tok")
    client = MailboxApiClient()
    assert client.base_url == "http://elsewhere:9"
    assert client._http.headers["authorization"] == "Bearer tok"
    await client.aclose()


async def test_defaults_without_environment() -> None:
    client = MailboxApiClient()
    assert client.base_url == DEFAULT_URL
    assert "authorization" not in client._http.headers
    await client.aclose()


async def test_ids_are_quoted_in_paths(make_client: Callable) -> None:
    """An id comes from the model: it must not carry a path of its own."""
    seen: list[httpx.Request] = []

    def handler(request: httpx.Request) -> httpx.Response:
        seen.append(request)
        return httpx.Response(200, json={"id": "x"})

    client = make_client(handler)
    await client.get_message("acc_1", "../users")
    assert seen[0].url.raw_path == b"/v1/accounts/acc_1/messages/..%2Fusers"
    await client.aclose()
