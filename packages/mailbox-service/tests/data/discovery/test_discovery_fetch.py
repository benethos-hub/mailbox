"""The guarded HTTPS fetch of autodiscovery, offline."""

from __future__ import annotations

from typing import Any

import httpx
import pytest

from benethos_mailbox_service.data.protocols.http import SafeFetcher
from benethos_mailbox_service.errors import ProviderError, ProviderUnavailableError

from ...conftest import PUBLIC

PUBLIC_2 = "93.184.215.15"


def resolver(table: dict[str, list[str]]) -> Any:
    async def resolve(host: str, port: int) -> list[str]:
        return table.get(host, [])

    return resolve


def fetcher(
    handler: Any, table: dict[str, list[str]], **kwargs: Any
) -> tuple[SafeFetcher, list[httpx.Request]]:
    seen: list[httpx.Request] = []

    def record(request: httpx.Request) -> httpx.Response:
        seen.append(request)
        result: httpx.Response = handler(request)
        return result

    return (
        SafeFetcher(
            resolve=resolver(table), transport=httpx.MockTransport(record), **kwargs
        ),
        seen,
    )


async def test_fetch_pins_the_checked_address() -> None:
    f, seen = fetcher(
        lambda r: httpx.Response(200, content=b"<ok/>"),
        {"autoconfig.example.com": [PUBLIC]},
    )
    result = await f.get("https://autoconfig.example.com/mail/config-v1.1.xml?x=1")
    assert result is not None
    assert result.body == b"<ok/>"
    assert result.host == "autoconfig.example.com"
    [request] = seen
    assert request.url.host == PUBLIC
    assert request.url.query == b"x=1"
    assert request.headers["host"] == "autoconfig.example.com"
    assert request.extensions["sni_hostname"] == "autoconfig.example.com"


async def test_fetch_nothing_when_the_host_does_not_resolve() -> None:
    f, seen = fetcher(lambda r: httpx.Response(200), {})
    assert await f.get("https://autoconfig.example.com/x") is None
    assert seen == []


async def test_fetch_nothing_on_other_status() -> None:
    f, _ = fetcher(lambda r: httpx.Response(404), {"example.com": [PUBLIC]})
    assert await f.get("https://example.com/x") is None


async def test_fetch_refuses_http() -> None:
    f, seen = fetcher(lambda r: httpx.Response(200), {"example.com": [PUBLIC]})
    with pytest.raises(ProviderError, match="HTTPS only"):
        await f.get("http://example.com/x")
    assert seen == []


@pytest.mark.parametrize("private", ["127.0.0.1", "10.0.0.5", "::1", "169.254.1.1"])
async def test_fetch_refuses_private_addresses(private: str) -> None:
    f, seen = fetcher(
        lambda r: httpx.Response(200), {"evil.example": [PUBLIC, private]}
    )
    with pytest.raises(ProviderError, match="non-public"):
        await f.get("https://evil.example/x")
    assert seen == []


async def test_fetch_allows_internal_hosts_by_name() -> None:
    f, seen = fetcher(
        lambda r: httpx.Response(200, content=b"ok"),
        {"mail.intern.example": ["10.0.0.5"]},
        internal_hosts=["Mail.Intern.Example."],
    )
    result = await f.get("https://mail.intern.example/x")
    assert result is not None and result.body == b"ok"
    assert seen[0].url.host == "10.0.0.5"


async def test_fetch_follows_redirects_and_checks_each_hop() -> None:
    def handler(request: httpx.Request) -> httpx.Response:
        host = request.headers["host"]
        if host == "autoconfig.example.com":
            return httpx.Response(
                301, headers={"location": "https://config.hoster.example/c.xml"}
            )
        return httpx.Response(200, content=b"final")

    f, seen = fetcher(
        handler,
        {"autoconfig.example.com": [PUBLIC], "config.hoster.example": [PUBLIC_2]},
    )
    result = await f.get("https://autoconfig.example.com/x")
    assert result is not None
    assert result.body == b"final"
    assert result.host == "config.hoster.example"
    assert seen[-1].url.path == "/c.xml"
    assert [r.url.host for r in seen] == [PUBLIC, PUBLIC_2]


async def test_fetch_relative_redirect() -> None:
    def handler(request: httpx.Request) -> httpx.Response:
        if request.url.path == "/a":
            return httpx.Response(302, headers={"location": "/b"})
        return httpx.Response(200, content=request.url.path.encode())

    f, _ = fetcher(handler, {"example.com": [PUBLIC]})
    result = await f.get("https://example.com/a")
    assert result is not None and result.body == b"/b"


async def test_fetch_redirect_to_a_private_address_is_refused() -> None:
    f, seen = fetcher(
        lambda r: httpx.Response(302, headers={"location": "https://inside.example/"}),
        {"example.com": [PUBLIC], "inside.example": ["192.168.1.1"]},
    )
    with pytest.raises(ProviderError, match="non-public"):
        await f.get("https://example.com/")
    assert len(seen) == 1


async def test_fetch_redirect_to_a_location_that_is_no_url() -> None:
    f, _ = fetcher(
        lambda r: httpx.Response(302, headers={"location": "https://[::1"}),
        {"example.com": [PUBLIC]},
    )
    with pytest.raises(ProviderError, match="not reachable"):
        await f.get("https://example.com/")


async def test_fetch_of_what_is_no_url() -> None:
    f, _ = fetcher(lambda r: httpx.Response(200), {"example.com": [PUBLIC]})
    with pytest.raises(ProviderError, match="not a URL"):
        await f.get("https://[::1")


async def test_fetch_redirect_to_http_is_refused() -> None:
    f, _ = fetcher(
        lambda r: httpx.Response(302, headers={"location": "http://example.com/"}),
        {"example.com": [PUBLIC]},
    )
    with pytest.raises(ProviderError, match="HTTPS only"):
        await f.get("https://example.com/")


async def test_fetch_redirect_without_location_is_nothing() -> None:
    f, _ = fetcher(lambda r: httpx.Response(302), {"example.com": [PUBLIC]})
    assert await f.get("https://example.com/") is None


async def test_fetch_stops_after_three_redirects() -> None:
    f, seen = fetcher(
        lambda r: httpx.Response(302, headers={"location": "/again"}),
        {"example.com": [PUBLIC]},
    )
    with pytest.raises(ProviderError, match="redirects"):
        await f.get("https://example.com/")
    assert len(seen) == 4


async def test_fetch_size_limit() -> None:
    f, _ = fetcher(
        lambda r: httpx.Response(200, content=b"x" * 2000),
        {"example.com": [PUBLIC]},
        max_bytes=1000,
    )
    with pytest.raises(ProviderError, match="larger than 1000 bytes"):
        await f.get("https://example.com/")


async def test_fetch_network_errors_are_unavailable() -> None:
    def timeout(request: httpx.Request) -> httpx.Response:
        raise httpx.ReadTimeout("slow", request=request)

    def refused(request: httpx.Request) -> httpx.Response:
        raise httpx.ConnectError("refused", request=request)

    for handler, text in [(timeout, "in time"), (refused, "not reachable")]:
        f, _ = fetcher(handler, {"example.com": [PUBLIC]})
        with pytest.raises(ProviderUnavailableError, match=text):
            await f.get("https://example.com/")
