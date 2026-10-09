"""How an answer or a failure on the way is read: the error envelope,
answers that are not JSON or not of the shape the API describes, no
content, a service that cannot be reached or does not answer in time."""

from __future__ import annotations

from collections.abc import Callable

import httpx
import pytest

from benethos_mailbox_client import (
    ApiError,
    MailboxError,
    ServiceTimeoutError,
    ServiceUnavailableError,
)


async def test_error_envelope_becomes_api_error(make_client: Callable) -> None:
    client = make_client(
        lambda _: httpx.Response(
            404, json={"error": {"code": "not_found", "message": "gone"}}
        )
    )
    with pytest.raises(ApiError, match=r"gone \(not_found, HTTP 404\)") as caught:
        await client.request("GET", "/v1/accounts/x")
    assert (caught.value.status, caught.value.code) == (404, "not_found")
    assert caught.value.message == "gone"


async def test_unexpected_error_body(make_client: Callable) -> None:
    client = make_client(lambda _: httpx.Response(500, text="boom"))
    with pytest.raises(ApiError) as exc:
        await client.request("GET", "/v1/accounts")
    assert exc.value.code == "unexpected_response"


async def test_a_validation_failure_names_what_was_wrong(make_client: Callable) -> None:
    client = make_client(
        lambda _: httpx.Response(
            422,
            json={
                "detail": [
                    {"type": "missing", "loc": ["body", "to"], "msg": "Field required"},
                    {"type": "x", "loc": ["query", "limit"], "msg": "too big"},
                ]
            },
        )
    )
    with pytest.raises(ApiError, match=r"to: Field required; query.limit: too big"):
        await client.request("POST", "/v1/accounts/x/send", json={})


async def test_an_answer_that_is_not_json(make_client: Callable) -> None:
    client = make_client(lambda _: httpx.Response(200, text="<html>proxy</html>"))
    with pytest.raises(ApiError, match="not JSON"):
        await client.request("GET", "/v1/accounts")


@pytest.mark.parametrize(
    "body",
    [
        {"accounts": [{"email": "a@example.org"}]},  # no id
        {"accounts": "all"},
        [],
    ],
)
async def test_an_answer_of_another_shape(make_client: Callable, body: object) -> None:
    client = make_client(lambda _: httpx.Response(200, json=body))
    with pytest.raises(ApiError) as exc:
        await client.get_me()
    assert exc.value.code == "unexpected_response"
    assert exc.value.status == 200


async def test_no_content(make_client: Callable) -> None:
    client = make_client(lambda _: httpx.Response(204))
    assert await client.request("DELETE", "/v1/accounts/x") is None


async def test_unreachable_service_says_what_to_do(make_client: Callable) -> None:
    def handler(request: httpx.Request) -> httpx.Response:
        raise httpx.ConnectError("refused", request=request)

    client = make_client(handler)
    with pytest.raises(ServiceUnavailableError, match="benethos-mailbox-service serve"):
        await client.request("GET", "/v1/accounts")
    with pytest.raises(ServiceUnavailableError):
        await client.get_attachment("acc_1", "msg_1", "att_0", max_bytes=10)


async def test_a_slow_answer_is_no_unreachable_service(make_client: Callable) -> None:
    def handler(request: httpx.Request) -> httpx.Response:
        raise httpx.ReadTimeout("slow", request=request)

    client = make_client(handler)
    with pytest.raises(ServiceTimeoutError, match="did not answer within 30 s"):
        await client.request("GET", "/v1/messages")
    with pytest.raises(ServiceTimeoutError, match="within 120 s"):
        await client.get_attachment("acc_1", "msg_1", "att_0", max_bytes=10)


async def test_a_connection_that_times_out_is_unreachable(
    make_client: Callable,
) -> None:
    def handler(request: httpx.Request) -> httpx.Response:
        raise httpx.ConnectTimeout("no answer", request=request)

    client = make_client(handler)
    with pytest.raises(ServiceUnavailableError, match="not reachable"):
        await client.request("GET", "/v1/accounts")


async def test_every_error_is_a_mailbox_error(make_client: Callable) -> None:
    client = make_client(lambda _: httpx.Response(500, text="boom"))
    with pytest.raises(MailboxError):
        await client.get_me()
