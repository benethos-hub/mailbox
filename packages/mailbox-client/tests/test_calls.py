"""The request a call makes: what stays out of it, and how an id is
quoted in its path."""

from __future__ import annotations

from collections.abc import Callable

import httpx


async def test_none_stays_out_of_a_request(make_client: Callable) -> None:
    seen: list[httpx.Request] = []

    def handler(request: httpx.Request) -> httpx.Response:
        seen.append(request)
        return httpx.Response(200, json={})

    client = make_client(handler)
    await client.request(
        "POST", "/v1/x", params={"a": 1, "b": None}, json={"c": None, "d": 2}
    )
    assert dict(seen[0].url.params) == {"a": "1"}
    assert seen[0].content == b'{"d":2}'


async def test_ids_are_quoted_in_paths(make_client: Callable) -> None:
    """An id may come from anyone: it must not carry a path of its own."""
    seen: list[httpx.Request] = []

    def handler(request: httpx.Request) -> httpx.Response:
        seen.append(request)
        return httpx.Response(200, json={"id": "x"})

    client = make_client(handler)
    await client.get_message("acc_1", "../users")
    assert seen[0].url.raw_path == b"/v1/accounts/acc_1/messages/..%2Fusers"
