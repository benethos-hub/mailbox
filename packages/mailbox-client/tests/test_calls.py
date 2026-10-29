"""The request a call makes: what stays out of it, how an id is quoted
in its path, and what its repr leaves out."""

from __future__ import annotations

from collections.abc import Callable

import httpx

from benethos_mailbox_client import endpoints


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


def test_the_repr_of_a_call_leaves_out_its_body_and_headers() -> None:
    made = endpoints.create_account(
        "imap", "me@example.org", credentials={"password": "pw_SECRET"}
    )
    assert made.json is not None and made.json["credentials"]["password"] == "pw_SECRET"
    assert "pw_SECRET" not in repr(made)
    sent = endpoints.send_draft("acc_1", "drf_1", "key_SECRET")
    assert "key_SECRET" not in repr(sent)
