"""JMAP on the wire: the session, requests the server refuses, its errors,
and the event stream. The client talks to a handler of each test's own."""

from __future__ import annotations

from collections.abc import AsyncIterator, Callable
from typing import Any

import httpx
import pytest

from benethos_mailbox_service.data.protocols import ServerClient, jmap
from benethos_mailbox_service.data.protocols.http import server as http_server
from benethos_mailbox_service.errors import (
    BadRequestError,
    ChangesExpiredError,
    ConflictError,
    NotFoundError,
    NotSupportedError,
    ProviderAuthError,
    ProviderError,
    ProviderUnavailableError,
)

from ...jmap_fake import FakeJmap

Handler = Callable[[httpx.Request], Any]


def client(
    handler: Handler,
    *,
    host: str = "jmap.example.com",
    port: int = 443,
    path: str = "/.well-known/jmap",
    clock: Callable[[], float] = lambda: 0.0,
) -> jmap.JmapClient:
    return jmap.JmapClient(
        jmap.JmapServer(host=host, port=port, path=path),
        lambda: "Bearer t",
        http=ServerClient(transport=httpx.MockTransport(handler)),
        clock=clock,
    )


def session_body(**changes: Any) -> dict[str, Any]:
    return {**FakeJmap().session(), **changes}


async def test_a_redirect_to_another_server_is_refused() -> None:
    def handler(request: httpx.Request) -> httpx.Response:
        return httpx.Response(
            307, headers={"Location": "https://elsewhere.example.org/jmap/session"}
        )

    with pytest.raises(ProviderError, match="another server"):
        await client(handler).session()


async def test_a_redirect_with_the_same_server_named_in_full() -> None:
    def handler(request: httpx.Request) -> httpx.Response:
        if request.url.path == "/.well-known/jmap":
            return httpx.Response(
                301, headers={"Location": "https://JMAP.example.com:443/s?x=1"}
            )
        assert request.url.query == b"x=1"
        return httpx.Response(200, json=session_body())

    found = await client(handler).session()
    assert found.account_id == "acc1" and found.api == "/jmap/"


@pytest.mark.parametrize(
    ("location", "message"),
    [("", "without a path"), ("relative", "without a path")],
)
async def test_redirects_without_a_path(location: str, message: str) -> None:
    def handler(request: httpx.Request) -> httpx.Response:
        return httpx.Response(302, headers={"Location": location})

    with pytest.raises(ProviderError, match=message):
        await client(handler).session()


async def test_endless_redirects() -> None:
    def handler(request: httpx.Request) -> httpx.Response:
        return httpx.Response(302, headers={"Location": "/again"})

    with pytest.raises(ProviderError, match="redirects more than"):
        await client(handler).session()


@pytest.mark.parametrize(
    ("body", "message"),
    [
        ([], "no JSON object"),
        ({"capabilities": {}}, "no JMAP mail"),
        (session_body(apiUrl=None), "lacks a URL"),
        (session_body(apiUrl="no-path"), "without a path"),
    ],
)
async def test_sessions_that_cannot_serve(body: Any, message: str) -> None:
    def handler(request: httpx.Request) -> httpx.Response:
        return httpx.Response(200, json=body)

    with pytest.raises(ProviderError, match=message):
        await client(handler, path="/s").session()


async def test_the_session_is_read_again_when_it_changed() -> None:
    reads = []

    def handler(request: httpx.Request) -> httpx.Response:
        if request.url.path == "/s":
            reads.append(1)
            return httpx.Response(200, json=session_body())
        return httpx.Response(
            200, json={"methodResponses": [], "sessionState": f"s{len(reads) + 1}"}
        )

    wire = client(handler, path="/s")
    await wire.call([])
    await wire.call([])
    assert len(reads) == 2


@pytest.mark.parametrize(
    ("answer", "error", "message"),
    [
        (httpx.Response(401), ProviderAuthError, "refused the credential"),
        (httpx.Response(403), ProviderAuthError, "refused access"),
        (httpx.Response(404), NotFoundError, "404"),
        (httpx.Response(413), BadRequestError, "413"),
        (httpx.Response(502), ProviderUnavailableError, "busy"),
        (
            httpx.Response(
                400,
                json={"type": "urn:ietf:params:jmap:error:limit", "detail": "too many"},
            ),
            ProviderError,
            "too many",
        ),
        (httpx.Response(500, content=b"<html>"), ProviderError, "refused"),
        (httpx.Response(200, json={"no": "responses"}), ProviderError, "without"),
    ],
)
async def test_requests_the_server_refuses(
    answer: httpx.Response, error: type[Exception], message: str
) -> None:
    def handler(request: httpx.Request) -> httpx.Response:
        if request.url.path == "/s":
            return httpx.Response(200, json=session_body())
        return answer

    with pytest.raises(error, match=message):
        await client(handler, path="/s").call([])


async def test_a_server_that_asks_to_wait_is_left_alone() -> None:
    now = [100.0]
    sent = []

    def handler(request: httpx.Request) -> httpx.Response:
        if request.url.path == "/s":
            return httpx.Response(200, json=session_body())
        sent.append(1)
        return httpx.Response(429, headers={"Retry-After": "30"})

    wire = client(handler, path="/s", clock=lambda: now[0])
    with pytest.raises(ProviderUnavailableError, match="retry after 30s"):
        await wire.call([])
    with pytest.raises(ProviderUnavailableError, match="next attempt in 30s"):
        await wire.call([])
    assert sent == [1]
    now[0] += 31
    with pytest.raises(ProviderUnavailableError):
        await wire.call([])
    assert sent == [1, 1]


async def test_odd_responses_are_left_out() -> None:
    def handler(request: httpx.Request) -> httpx.Response:
        if request.url.path == "/s":
            return httpx.Response(200, json=session_body())
        return httpx.Response(
            200, json={"methodResponses": [["Email/get", {}, "a"], "odd", [1, 2, 3]]}
        )

    answers = await client(handler, path="/s").call([("Email/get", {}, "a")])
    assert answers == [("Email/get", {}, "a")]
    with pytest.raises(ProviderError, match="unanswered"):
        jmap.result(answers, "b")
    assert jmap.error_type(answers, "a") is None


async def test_uploads_and_downloads_the_server_refuses() -> None:
    def handler(request: httpx.Request) -> httpx.Response:
        if request.url.path == "/s":
            return httpx.Response(200, json=session_body())
        if "upload" in request.url.path:
            return httpx.Response(201, json={"size": 1})
        return httpx.Response(500)

    wire = client(handler, path="/s")
    with pytest.raises(ProviderError, match="without a blob id"):
        await wire.upload(b"x", "message/rfc822")
    with pytest.raises(ProviderError):
        await wire.download("b1", "a", "message/rfc822")

    def refusing(request: httpx.Request) -> httpx.Response:
        if request.url.path == "/s":
            return httpx.Response(200, json=session_body())
        return httpx.Response(413)

    with pytest.raises(BadRequestError):
        await client(refusing, path="/s").upload(b"x", "message/rfc822")


@pytest.mark.parametrize(
    ("kind", "error"),
    [
        ("cannotCalculateChanges", ChangesExpiredError),
        ("serverUnavailable", ProviderUnavailableError),
        ("rateLimit", ProviderUnavailableError),
        ("unknownMethod", NotSupportedError),
        ("invalidArguments", BadRequestError),
        ("forbidden", ProviderAuthError),
        ("serverFail", ProviderError),
    ],
)
def test_method_errors(kind: str, error: type[Exception]) -> None:
    assert type(jmap.method_error({"type": kind})) is error


@pytest.mark.parametrize(
    ("kind", "error"),
    [
        ("notFound", NotFoundError),
        ("alreadyExists", ConflictError),
        ("forbiddenToSend", ConflictError),
        ("invalidProperties", BadRequestError),
        ("somethingNew", ProviderError),
    ],
)
def test_set_errors(kind: str, error: type[Exception]) -> None:
    assert type(jmap.set_error(jmap.SetError(type=kind), "message")) is error


async def test_an_event_source_that_refuses() -> None:
    def handler(request: httpx.Request) -> httpx.Response:
        if request.url.path == "/s":
            return httpx.Response(200, json=session_body())
        return httpx.Response(401)

    with pytest.raises(ProviderAuthError):
        async with client(handler, path="/s").events("Email", 60, 1):
            pass


async def test_events_that_are_not_state_changes() -> None:
    lines = [
        "event: state",
        "data: not json",
        "",
        "event: other",
        'data: {"changed": {"a": {}}}',
        "",
        ": a comment",
        'data: {"changed": {"acc1": {"Email": "s2"}}}',
        "",
    ]

    async def stream() -> AsyncIterator[bytes]:
        yield "\r\n".join(lines).encode()
        yield b"\r\n"

    def handler(request: httpx.Request) -> httpx.Response:
        if request.url.path == "/s":
            return httpx.Response(200, json=session_body())
        return httpx.Response(200, content=stream())

    async with client(handler, path="/s").events("Email", 60, 1) as changes:
        found = [changed async for changed in changes]
    assert found == [{"acc1": {"Email": "s2"}}]


async def test_a_line_too_long_is_refused(monkeypatch: pytest.MonkeyPatch) -> None:
    monkeypatch.setattr(http_server, "MAX_LINE", 10)

    async def stream() -> AsyncIterator[bytes]:
        yield b"data: " + b"x" * 20

    def handler(request: httpx.Request) -> httpx.Response:
        if request.url.path == "/s":
            return httpx.Response(200, json=session_body())
        return httpx.Response(200, content=stream())

    with pytest.raises(ProviderError, match="longer than"):
        async with client(handler, path="/s").events("Email", 60, 1) as changes:
            async for _ in changes:
                pass


# --- the HTTP client below ------------------------------------------------------------


async def test_the_client_goes_to_the_address_pick_checked() -> None:
    picked = []

    def pick(host: str, port: int) -> str:
        picked.append((host, port))
        return "192.0.2.7"

    def handler(request: httpx.Request) -> httpx.Response:
        assert request.url.host == "192.0.2.7"
        assert request.headers["host"] == "jmap.example.com:8443"
        assert request.extensions["sni_hostname"] == "jmap.example.com"
        assert request.headers["content-type"] == "application/json"
        return httpx.Response(200, json={})

    http = ServerClient(pick=pick, transport=httpx.MockTransport(handler))
    answer = await http.request(
        "POST", "https://jmap.example.com:8443/x", json_body={"a": 1}
    )
    assert answer.status == 200 and picked == [("jmap.example.com", 8443)]


async def test_the_client_wants_https() -> None:
    http = ServerClient(transport=httpx.MockTransport(lambda r: httpx.Response(200)))
    with pytest.raises(ProviderError, match="without HTTPS"):
        await http.request("GET", "http://jmap.example.com/x")


async def test_a_server_that_cannot_be_reached() -> None:
    def handler(request: httpx.Request) -> httpx.Response:
        raise httpx.ConnectError("refused")

    http = ServerClient(transport=httpx.MockTransport(handler))
    with pytest.raises(ProviderUnavailableError, match="not reachable"):
        await http.request("GET", "https://jmap.example.com/x")
    with pytest.raises(ProviderUnavailableError, match="not reachable"):
        async with http.lines("https://jmap.example.com/x", wait=1):
            pass


def test_an_ipv6_server_in_a_url() -> None:
    assert jmap.JmapServer(host="::1", port=30443).url("/s") == "https://[::1]:30443/s"
