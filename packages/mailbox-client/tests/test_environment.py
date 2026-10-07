"""The address and the token: from the environment or given, checked
before a client is made, and sent with every request."""

from __future__ import annotations

from collections.abc import Callable

import httpx
import pytest

from benethos_mailbox_client import (
    ConfigurationError,
    Environment,
    MailboxClient,
    SyncMailboxClient,
    from_environment,
)
from benethos_mailbox_client.environment import DEFAULT_URL

ACCOUNT = {"id": "acc_1", "provider": "imap", "email": "me@example.com"}
KINDS = [MailboxClient, SyncMailboxClient]


async def test_sends_bearer_and_parses(make_client: Callable) -> None:
    seen: list[httpx.Request] = []

    def handler(request: httpx.Request) -> httpx.Response:
        seen.append(request)
        return httpx.Response(200, json=[ACCOUNT])

    client = make_client(handler)
    assert await client.request("GET", "/v1/accounts") == [ACCOUNT]
    assert seen[0].headers["authorization"] == "Bearer secret"
    assert seen[0].url == "https://mail.test/v1/accounts"


def recording(seen: list[httpx.Request]) -> httpx.MockTransport:
    def handler(request: httpx.Request) -> httpx.Response:
        seen.append(request)
        return httpx.Response(200, json=[])

    return httpx.MockTransport(handler)


async def test_url_and_token_from_environment(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    monkeypatch.setenv("MAILBOX_SERVICE_URL", "https://elsewhere:9/")
    monkeypatch.setenv("MAILBOX_SERVICE_TOKEN", "tok")
    seen: list[httpx.Request] = []
    async with MailboxClient(transport=recording(seen)) as client:
        await client.request("GET", "/v1/accounts")
    with SyncMailboxClient(transport=recording(seen)) as sync:
        sync.request("GET", "/v1/accounts")
    for request in seen:
        assert request.url == "https://elsewhere:9/v1/accounts"
        assert request.headers["authorization"] == "Bearer tok"


@pytest.mark.parametrize("kind", KINDS)
@pytest.mark.parametrize(
    "url",
    [
        "http://127.0.0.1:8080",
        "http://127.0.0.2",
        "http://localhost:8080",
        "http://[::1]:8080",
        "https://mail.example.org",
    ],
)
def test_urls_that_keep_the_token_safe(kind: type, url: str) -> None:
    kind(base_url=url, token="tok", allow_http=False)


@pytest.mark.parametrize("kind", KINDS)
@pytest.mark.parametrize(
    "url",
    ["http://mailbox-service:8080", "http://10.0.0.5", "http://mail.example.org"],
)
def test_http_to_another_machine_needs_to_be_allowed(
    monkeypatch: pytest.MonkeyPatch, kind: type, url: str
) -> None:
    with pytest.raises(ConfigurationError, match="MAILBOX_SERVICE_ALLOW_HTTP=1"):
        kind(base_url=url, token="tok")
    monkeypatch.setenv("MAILBOX_SERVICE_ALLOW_HTTP", "1")
    kind(base_url=url, token="tok")


@pytest.mark.parametrize("kind", KINDS)
@pytest.mark.parametrize("url", ["ftp://mail.example.org", "mail.example.org"])
def test_only_http_and_https(kind: type, url: str) -> None:
    with pytest.raises(ConfigurationError, match="http or https"):
        kind(base_url=url, token="tok", allow_http=True)


def test_a_url_that_is_not_one() -> None:
    with pytest.raises(ConfigurationError, match="not a URL"):
        SyncMailboxClient(base_url="http://[::1", token="tok")


async def test_defaults_without_environment() -> None:
    seen: list[httpx.Request] = []
    async with MailboxClient(token="tok", transport=recording(seen)) as client:
        await client.request("GET", "/v1/accounts")
    assert str(seen[0].url).startswith(DEFAULT_URL)


@pytest.mark.parametrize("kind", KINDS)
@pytest.mark.parametrize("token", [None, ""])
def test_no_token_names_the_variable(kind: type, token: str | None) -> None:
    with pytest.raises(ConfigurationError, match="MAILBOX_SERVICE_TOKEN is not set"):
        kind(token=token)


def test_the_environment_is_read_at_one_moment(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    """A program that makes clients for a long time reads it once: what
    changes later reaches none of them."""
    monkeypatch.setenv("MAILBOX_SERVICE_URL", "http://mailbox-service:8080/")
    monkeypatch.setenv("MAILBOX_SERVICE_TOKEN", "tok")
    monkeypatch.setenv("MAILBOX_SERVICE_ALLOW_HTTP", " True ")
    found = from_environment()
    assert found == Environment("http://mailbox-service:8080", "tok", True)
    monkeypatch.delenv("MAILBOX_SERVICE_ALLOW_HTTP")
    client = MailboxClient(found.url, found.token, allow_http=found.allow_http)
    assert client.base_url == "http://mailbox-service:8080"
