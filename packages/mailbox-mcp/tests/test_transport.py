"""The HTTP transport: bearer guard, host checks, the command line."""

from __future__ import annotations

import asyncio
import json
import logging
from typing import Any

import pytest
from starlette.testclient import TestClient

from benethos_mailbox_mcp import server, transport

TOKEN = "s3cret-token"


async def inner(scope: Any, receive: Any, send: Any) -> None:
    inner.reached = True  # type: ignore[attr-defined]
    await send({"type": "http.response.start", "status": 200, "headers": []})
    await send({"type": "http.response.body", "body": b"ok"})


def call(
    headers: list[tuple[bytes, bytes]], scope_type: str = "http"
) -> dict[str, Any]:
    inner.reached = False  # type: ignore[attr-defined]
    sent: list[dict[str, Any]] = []

    async def send(message: dict[str, Any]) -> None:
        sent.append(message)

    async def receive() -> dict[str, Any]:
        return {"type": "http.request"}

    app = transport.bearer_middleware(inner, TOKEN)
    asyncio.run(app({"type": scope_type, "headers": headers}, receive, send))
    start = next((m for m in sent if m["type"] == "http.response.start"), None)
    return {
        "status": start["status"] if start else None,
        "headers": dict(start["headers"]) if start else {},
        "body": b"".join(m.get("body", b"") for m in sent),
        "reached": inner.reached,  # type: ignore[attr-defined]
    }


# --- the guard ------------------------------------------------------------------------


def test_the_right_token_is_served() -> None:
    answer = call([(b"authorization", f"Bearer {TOKEN}".encode())])
    assert (answer["status"], answer["reached"]) == (200, True)


def test_the_scheme_ignores_case() -> None:
    assert call([(b"authorization", f"bearer {TOKEN}".encode())])["status"] == 200


@pytest.mark.parametrize(
    "value",
    [
        None,
        b"Bearer wrong",
        f"Bearer {TOKEN[:-1]}".encode(),
        f"Bearer {TOKEN}x".encode(),
        f"Basic {TOKEN}".encode(),
        TOKEN.encode(),
    ],
)
def test_anything_else_is_refused_alike(value: bytes | None) -> None:
    answer = call([] if value is None else [(b"authorization", value)])
    assert answer["status"] == 401
    assert answer["reached"] is False
    assert answer["headers"][b"www-authenticate"] == b"Bearer"
    assert json.loads(answer["body"])["error"]["code"] == "unauthorized"


def test_lifespan_passes() -> None:
    assert call([], scope_type="lifespan")["reached"] is True


def test_a_websocket_is_closed_unseen() -> None:
    answer = call([(b"authorization", f"Bearer {TOKEN}".encode())], "websocket")
    assert answer["reached"] is False


def test_token_from_env(monkeypatch: pytest.MonkeyPatch) -> None:
    monkeypatch.delenv(transport.ENV_VAR, raising=False)
    assert transport.token_from_env() is None
    monkeypatch.setenv(transport.ENV_VAR, "   ")
    assert transport.token_from_env() is None
    monkeypatch.setenv(transport.ENV_VAR, " abc \n")
    assert transport.token_from_env() == "abc"


# --- host checks ----------------------------------------------------------------------


def test_a_loopback_bind_admits_loopback_names() -> None:
    security = transport.transport_security("127.0.0.1", [], [])
    assert security.enable_dns_rebinding_protection
    assert "localhost:*" in (security.allowed_hosts or [])


def test_an_explicit_list_wins() -> None:
    security = transport.transport_security("0.0.0.0", ["mcp.example.org:443"], [])
    assert security.allowed_hosts == ["mcp.example.org:443"]
    assert security.allowed_origins == [
        "http://mcp.example.org:443",
        "https://mcp.example.org:443",
    ]


def test_origins_alone_admit_their_hosts() -> None:
    security = transport.transport_security(
        "0.0.0.0", [], ["https://mcp.example.org", "http://box.local:8000"]
    )
    assert security.allowed_hosts == ["mcp.example.org", "box.local:8000"]
    assert security.allowed_origins == [
        "https://mcp.example.org",
        "http://box.local:8000",
    ]


def test_an_open_bind_without_a_list_checks_nothing() -> None:
    security = transport.transport_security("0.0.0.0", [], [])
    assert not security.enable_dns_rebinding_protection


# --- end to end, in process -----------------------------------------------------------

INITIALIZE = {
    "jsonrpc": "2.0",
    "id": 1,
    "method": "initialize",
    "params": {
        "protocolVersion": "2025-06-18",
        "capabilities": {},
        "clientInfo": {"name": "test", "version": "0"},
    },
}
MCP_HEADERS = {"Accept": "application/json, text/event-stream"}


def test_the_app_speaks_mcp_behind_the_guard() -> None:
    app = transport.http_app(
        server.build_server([]),
        path="/mcp",
        host="127.0.0.1",
        security=transport.transport_security("127.0.0.1", [], []),
        token=TOKEN,
    )
    with TestClient(app, base_url="http://127.0.0.1:8000") as client:
        refused = client.post("/mcp", json=INITIALIZE, headers=MCP_HEADERS)
        assert refused.status_code == 401
        served = client.post(
            "/mcp",
            json=INITIALIZE,
            headers={**MCP_HEADERS, "Authorization": f"Bearer {TOKEN}"},
        )
        assert served.status_code == 200
        assert "benethos-mailbox-mcp" in served.text


def test_a_foreign_host_is_refused() -> None:
    app = transport.http_app(
        server.build_server([]),
        path="/mcp",
        host="127.0.0.1",
        security=transport.transport_security("127.0.0.1", [], []),
        token=None,
    )
    with TestClient(app, base_url="http://evil.example:8000") as client:
        answer = client.post("/mcp", json=INITIALIZE, headers=MCP_HEADERS)
        assert answer.status_code == 421


# --- the command line -----------------------------------------------------------------


@pytest.fixture
def started(monkeypatch: pytest.MonkeyPatch) -> dict[str, Any]:
    """``main`` without the service and without binding a port."""
    seen: dict[str, Any] = {}

    async def operations() -> set[str]:
        return {"get_message"}

    def http_app(app_server: Any, **options: Any) -> str:
        seen["app"] = options
        return "app"

    def run_http(app: Any, **options: Any) -> None:
        seen["run"] = options

    class Stdio:
        def run(self, transport: str) -> None:
            seen["stdio"] = transport

    monkeypatch.setattr(server, "allowed_operations", operations)
    monkeypatch.setattr(transport, "http_app", http_app)
    monkeypatch.setattr(transport, "run_http", run_http)
    real_build = server.build_server
    monkeypatch.setattr(
        server,
        "build_server",
        lambda ops: Stdio() if seen.get("want_stdio") else real_build(ops),
    )
    for name in ("TRANSPORT", "HOST", "PORT", "PATH", "ALLOWED_HOSTS", "BEARER_TOKEN"):
        monkeypatch.delenv(f"MAILBOX_MCP_{name}", raising=False)
    return seen


def test_http_from_the_command_line(
    started: dict[str, Any], monkeypatch: pytest.MonkeyPatch
) -> None:
    monkeypatch.setenv(transport.ENV_VAR, TOKEN)
    server.main(["--transport", "streamable-http", "--port", "9001"])
    assert started["run"] == {"host": "127.0.0.1", "port": 9001, "log_level": "INFO"}
    assert started["app"]["path"] == "/mcp"
    assert started["app"]["token"] == TOKEN


def test_http_from_the_environment(
    started: dict[str, Any], monkeypatch: pytest.MonkeyPatch
) -> None:
    monkeypatch.setenv("MAILBOX_MCP_TRANSPORT", "streamable-http")
    monkeypatch.setenv("MAILBOX_MCP_HOST", "0.0.0.0")
    monkeypatch.setenv("MAILBOX_MCP_PATH", "/mail")
    monkeypatch.setenv("MAILBOX_MCP_ALLOWED_HOSTS", "a.example:443, b.example:443")
    server.main([])
    assert started["run"]["host"] == "0.0.0.0"
    assert started["app"]["path"] == "/mail"
    assert started["app"]["security"].allowed_hosts == [
        "a.example:443",
        "b.example:443",
    ]


def test_http_without_a_token_warns(
    started: dict[str, Any], caplog: pytest.LogCaptureFixture
) -> None:
    with caplog.at_level(logging.WARNING):
        server.main(["--transport", "streamable-http"])
    assert started["app"]["token"] is None
    assert transport.ENV_VAR in caplog.text


def test_stdio_ignores_a_token(
    started: dict[str, Any],
    monkeypatch: pytest.MonkeyPatch,
    caplog: pytest.LogCaptureFixture,
) -> None:
    started["want_stdio"] = True
    monkeypatch.setenv(transport.ENV_VAR, TOKEN)
    with caplog.at_level(logging.WARNING):
        server.main([])
    assert started["stdio"] == "stdio"
    assert "ignored" in caplog.text
    assert "app" not in started


def test_an_unknown_transport_from_the_environment(
    started: dict[str, Any], monkeypatch: pytest.MonkeyPatch
) -> None:
    monkeypatch.setenv("MAILBOX_MCP_TRANSPORT", "carrier-pigeon")
    with pytest.raises(SystemExit):
        server.main([])
