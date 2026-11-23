"""The model gateway behind llm/gateway.py, mocked."""

from __future__ import annotations

import json
import ssl
from collections.abc import AsyncIterator
from typing import Literal

import httpx
import pytest
from pydantic import BaseModel

from benethos_mailbox_agents.errors import (
    AnswerRefusedError,
    ConfigError,
    GatewayUnavailableError,
)
from benethos_mailbox_agents.llm.gateway import Gateway, strict_schema

from ..agents_fake import FakeGateway

OTHER = '{"label": "other", "quote": "q", "supplier": null}'

# Brackets nested deeper than any parser's stack holds: 20 000 raise a
# RecursionError on Windows, not on Linux from Python 3.14.
DEEP = 1_000_000


class Inner(BaseModel):
    value: str | None
    quote: str


class Answer(BaseModel):
    label: Literal["invoice", "other"]
    quote: str
    supplier: Inner | None = None


@pytest.fixture
def fake() -> FakeGateway:
    return FakeGateway(model="local-small-q4")


@pytest.fixture
async def gateway(fake: FakeGateway) -> AsyncIterator[Gateway]:
    async with Gateway(
        "https://gateway.example.test/v1/",
        "gateway-key",
        "classifier",
        timeout=120.0,
        transport=fake.transport(),
    ) as opened:
        yield opened


async def test_one_call_with_a_schema(fake: FakeGateway, gateway: Gateway) -> None:
    fake.answer({"label": "invoice", "quote": "Ihre Rechnung", "supplier": None})

    reply = await gateway.ask(system="You sort mail.", content="mail", schema=Answer)

    assert reply.value == Answer(label="invoice", quote="Ihre Rechnung")
    assert (reply.model, reply.tokens_in, reply.tokens_out) == (
        "local-small-q4",
        120,
        15,
    )
    (body,) = fake.bodies()
    assert body["model"] == "classifier"
    assert [m["role"] for m in body["messages"]] == ["system", "user"]
    assert body["response_format"]["json_schema"]["name"] == "Answer"
    assert "tools" not in body
    assert "temperature" not in body
    request = fake.requests[0]
    assert request.url.path == "/v1/chat/completions"
    assert request.headers["authorization"] == "Bearer gateway-key"


def test_the_strict_schema_closes_every_object() -> None:
    found = strict_schema(Answer)

    assert found["additionalProperties"] is False
    assert found["required"] == ["label", "quote", "supplier"]
    inner = found["$defs"]["Inner"]
    assert inner["additionalProperties"] is False
    assert inner["required"] == ["value", "quote"]


@pytest.mark.parametrize(
    "content",
    [
        "not json",
        '{"label": "maybe", "quote": "x"}',
        '{"quote": "x"}',
    ],
)
async def test_an_answer_outside_the_schema_is_refused(
    fake: FakeGateway, gateway: Gateway, content: str
) -> None:
    fake.answer(content)

    with pytest.raises(AnswerRefusedError) as raised:
        await gateway.ask(system="s", content="c", schema=Answer)

    assert raised.value.reason == "schema"


async def test_an_answer_without_choices_is_refused(
    fake: FakeGateway, gateway: Gateway
) -> None:
    fake.answer(httpx.Response(200, json={"choices": []}))

    with pytest.raises(AnswerRefusedError):
        await gateway.ask(system="s", content="c", schema=Answer)


async def test_an_answer_that_is_no_json_is_refused(
    fake: FakeGateway, gateway: Gateway
) -> None:
    fake.answer(httpx.Response(200, text="<html>"))

    with pytest.raises(AnswerRefusedError):
        await gateway.ask(system="s", content="c", schema=Answer)


@pytest.mark.parametrize("status", [500, 502, 503, 429, 408])
async def test_a_gateway_in_trouble_is_unavailable(
    fake: FakeGateway, gateway: Gateway, status: int
) -> None:
    fake.answer(httpx.Response(status))

    with pytest.raises(GatewayUnavailableError):
        await gateway.ask(system="s", content="c", schema=Answer)


@pytest.mark.parametrize("status", [401, 403, 404])
async def test_a_refused_key_or_alias_is_a_config_error(
    fake: FakeGateway, gateway: Gateway, status: int
) -> None:
    fake.answer(httpx.Response(status))

    with pytest.raises(ConfigError):
        await gateway.ask(system="s", content="c", schema=Answer)


async def test_a_refused_request_is_named(fake: FakeGateway, gateway: Gateway) -> None:
    fake.answer(httpx.Response(400, json={"error": {"message": "too long"}}))

    with pytest.raises(AnswerRefusedError) as raised:
        await gateway.ask(system="s", content="c", schema=Answer)

    assert raised.value.reason == "request"


@pytest.mark.parametrize(
    "failure", [httpx.ConnectError("no"), httpx.ReadTimeout("slow")]
)
async def test_a_gateway_out_of_reach_is_unavailable(
    failure: httpx.TransportError,
) -> None:
    def handler(request: httpx.Request) -> httpx.Response:
        raise failure

    async with Gateway(
        "https://gateway.example.test/v1",
        "k",
        "m",
        timeout=120.0,
        transport=httpx.MockTransport(handler),
    ) as gateway:
        with pytest.raises(GatewayUnavailableError):
            await gateway.ask(system="s", content="c", schema=Answer)


@pytest.mark.parametrize(
    ("url", "allow"),
    [
        ("https://gw.example.com/v1", False),
        ("http://127.0.0.1:4000/v1", False),
        ("http://localhost:4000/v1", False),
        ("http://[::1]:4000/v1", False),
        ("http://gw.example.com/v1", True),
    ],
)
async def test_a_gateway_url_that_keeps_the_key_safe(url: str, allow: bool) -> None:
    async with Gateway(url, "k", "m", timeout=120.0, allow_http=allow):
        pass


@pytest.mark.parametrize(
    "url", ["http://gw.example.com/v1", "http://10.0.0.5/v1", "ftp://gw/v1", "x"]
)
def test_http_to_another_machine_is_refused(url: str) -> None:
    with pytest.raises(ConfigError, match="MAILBOX_AGENTS_GATEWAY"):
        Gateway(url, "k", "m", timeout=120.0)


@pytest.mark.parametrize(
    "url",
    [
        "http://user:secret@127.0.0.1:4000",  # pragma: allowlist secret
        "https://user:secret@gateway.example",  # pragma: allowlist secret
        "https://user@gateway.example",
    ],
)
def test_a_user_or_password_in_the_gateway_url_is_refused(url: str) -> None:
    with pytest.raises(ConfigError, match="user or password") as refused:
        Gateway(url, "k", "m", timeout=120.0)
    assert "secret" not in str(refused.value)


async def test_the_alias_stands_in_when_no_model_is_reported(gateway: Gateway) -> None:
    transport = httpx.MockTransport(
        lambda request: httpx.Response(
            200,
            json={"choices": [{"message": {"content": OTHER}}]},
        )
    )
    async with Gateway(
        "https://g.example.test", "k", "alias", timeout=120.0, transport=transport
    ) as other:
        reply = await other.ask(system="s", content="c", schema=Answer)

    assert (reply.model, reply.tokens_in) == ("alias", 0)


@pytest.mark.parametrize(
    "usage",
    [
        "n/a",
        {"prompt_tokens": "n/a", "completion_tokens": "n/a"},
        {"prompt_tokens": -5, "completion_tokens": -1},
        {"prompt_tokens": float("inf"), "completion_tokens": [1]},
    ],
)
async def test_a_garbled_usage_counts_no_tokens(usage: object) -> None:
    """The call is made and paid: a count the gateway garbled must not end
    the process before the step is stored."""
    transport = httpx.MockTransport(
        lambda request: httpx.Response(
            200,
            content=json.dumps(
                {"choices": [{"message": {"content": OTHER}}], "usage": usage}
            ).replace("Infinity", "1e999"),
        )
    )
    async with Gateway(
        "https://g.example.test", "k", "alias", timeout=120.0, transport=transport
    ) as other:
        reply = await other.ask(system="s", content="c", schema=Answer)

    assert (reply.tokens_in, reply.tokens_out) == (0, 0)


def test_a_ca_of_the_settings_is_what_the_gateway_trusts(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    given: dict[str, object] = {}
    real = httpx.AsyncClient

    def client(**kwargs: object) -> httpx.AsyncClient:
        given.update(kwargs)
        return real(**kwargs)  # type: ignore[arg-type]

    monkeypatch.setattr(httpx, "AsyncClient", client)
    context = ssl.create_default_context()

    Gateway("https://g.example.test", "k", "m", timeout=1.0, verify=context)
    assert given["verify"] is context
    given.clear()
    Gateway("https://g.example.test", "k", "m", timeout=1.0)
    assert "verify" not in given
    assert given["trust_env"] is False


async def test_an_answer_with_a_lone_surrogate_is_refused(
    fake: FakeGateway, gateway: Gateway
) -> None:
    # The JSON escape of a lone surrogate passes json.loads and the schema,
    # but cannot be stored as UTF-8.
    fake.answer('{"label": "invoice", "quote": "R-1 \\ud800", "supplier": null}')

    with pytest.raises(AnswerRefusedError) as found:
        await gateway.ask(system="s", content="mail", schema=Answer)

    assert found.value.reason == "schema"


async def test_a_body_nested_too_deep_is_refused() -> None:
    deep = httpx.Response(200, content=b"[" * DEEP)
    async with Gateway(
        "https://gateway.example.test/v1/",
        "gateway-key",
        "classifier",
        timeout=120.0,
        transport=httpx.MockTransport(lambda request: deep),
    ) as opened:
        with pytest.raises(AnswerRefusedError) as found:
            await opened.ask(system="s", content="mail", schema=Answer)

    assert found.value.reason == "schema"


async def test_a_content_nested_too_deep_is_refused(
    fake: FakeGateway, gateway: Gateway
) -> None:
    fake.answer("[" * DEEP)

    with pytest.raises(AnswerRefusedError) as found:
        await gateway.ask(system="s", content="mail", schema=Answer)

    assert found.value.reason == "schema"


async def test_a_token_count_beyond_sqlite_is_capped(
    fake: FakeGateway, gateway: Gateway
) -> None:
    fake.answer(
        httpx.Response(
            200,
            json={
                "choices": [{"message": {"content": OTHER}}],
                "usage": {"prompt_tokens": 1e30, "completion_tokens": 10**40},
            },
        )
    )

    reply = await gateway.ask(system="s", content="mail", schema=Answer)

    assert (reply.tokens_in, reply.tokens_out) == (2**63 - 1, 2**63 - 1)


async def test_a_body_that_cannot_be_decoded_is_refused() -> None:
    def handle(request: httpx.Request) -> httpx.Response:
        return httpx.Response(
            200,
            headers={"content-encoding": "gzip"},
            stream=httpx.ByteStream(b"no gzip"),
        )

    async with Gateway(
        "https://gateway.example.test/v1/",
        "gateway-key",
        "classifier",
        timeout=120.0,
        transport=httpx.MockTransport(handle),
    ) as opened:
        with pytest.raises(AnswerRefusedError) as found:
            await opened.ask(system="s", content="mail", schema=Answer)

    assert found.value.reason == "schema"


async def test_a_redirect_is_a_configuration_to_correct(
    fake: FakeGateway, gateway: Gateway
) -> None:
    fake.answer(
        httpx.Response(307, headers={"location": "https://gateway.example.test/"})
    )

    with pytest.raises(ConfigError, match="MAILBOX_AGENTS_GATEWAY_URL"):
        await gateway.ask(system="s", content="mail", schema=Answer)
