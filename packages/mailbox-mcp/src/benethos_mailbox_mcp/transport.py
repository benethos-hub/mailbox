"""The MCP server over HTTP (streamable HTTP), behind a bearer guard.

The only module that imports ``uvicorn``. The SDK's own runner builds the
app and starts uvicorn in one step, which leaves nowhere to put the guard,
so the app is built here, wrapped, and served.

The guard admits callers with one shared token, ``MAILBOX_MCP_BEARER_TOKEN``.
It is not passed on: the server calls the REST API with its own
``MAILBOX_API_TOKEN``, whose user decides which tools exist.
"""

from __future__ import annotations

import hmac
import os
from typing import Any

from mcp.server.mcpserver import MCPServer
from mcp.server.transport_security import TransportSecuritySettings
from starlette.types import ASGIApp, Receive, Scope, Send

ENV_VAR = "MAILBOX_MCP_BEARER_TOKEN"

# The error envelope of the REST API.
_REFUSED = b'{"error":{"code":"unauthorized","message":"bearer token required"}}'

# Binds only this machine can reach.
LOCALHOST_BINDS = frozenset({"127.0.0.1", "localhost", "::1", ""})


def token_from_env() -> str | None:
    """The bearer token; unset or blank means no guard."""
    return (os.environ.get(ENV_VAR) or "").strip() or None


def bearer_middleware(app: ASGIApp, token: str) -> ASGIApp:
    """``app``, answering HTTP requests without ``Authorization: Bearer
    <token>`` with 401."""
    expected = token.encode()

    async def guarded(scope: Scope, receive: Receive, send: Send) -> None:
        if scope["type"] != "http":
            # lifespan must pass, or the session manager never starts.
            await app(scope, receive, send)
            return
        headers = dict(scope.get("headers") or [])
        scheme, _, provided = headers.get(b"authorization", b"").partition(b" ")
        # The scheme is case-insensitive (RFC 7235) and no secret; only the
        # token needs the constant-time comparison.
        if scheme.lower() != b"bearer" or not hmac.compare_digest(
            provided.strip(), expected
        ):
            await _unauthorized(send)
            return
        await app(scope, receive, send)

    return guarded


async def _unauthorized(send: Send) -> None:
    await send(
        {
            "type": "http.response.start",
            "status": 401,
            "headers": [
                (b"content-type", b"application/json"),
                (b"www-authenticate", b"Bearer"),
            ],
        }
    )
    # The same answer for a missing and a nearly right token.
    await send(
        {
            "type": "http.response.body",
            "body": _REFUSED,
        }
    )


def transport_security(
    host: str, allowed_hosts: list[str], allowed_origins: list[str]
) -> TransportSecuritySettings:
    """Host and Origin checks against DNS rebinding. An explicit list wins;
    a loopback bind admits the loopback names; any other bind without a list
    checks nothing, or every remote client would get 421."""
    if allowed_hosts or allowed_origins:
        origins = allowed_origins or [
            f"{scheme}://{h}" for h in allowed_hosts for scheme in ("http", "https")
        ]
        return TransportSecuritySettings(
            enable_dns_rebinding_protection=True,
            allowed_hosts=allowed_hosts,
            allowed_origins=origins,
        )
    if host in LOCALHOST_BINDS:
        return TransportSecuritySettings(
            enable_dns_rebinding_protection=True,
            allowed_hosts=["127.0.0.1:*", "localhost:*", "[::1]:*"],
            allowed_origins=[
                "http://127.0.0.1:*",
                "http://localhost:*",
                "http://[::1]:*",
            ],
        )
    return TransportSecuritySettings(enable_dns_rebinding_protection=False)


def http_app(
    server: MCPServer,
    *,
    path: str,
    host: str,
    security: TransportSecuritySettings,
    token: str | None,
) -> ASGIApp:
    app: ASGIApp = server.streamable_http_app(
        streamable_http_path=path, transport_security=security, host=host
    )
    return app if token is None else bearer_middleware(app, token)


def run_http(app: ASGIApp, *, host: str, port: int, log_level: str) -> None:
    import uvicorn

    config: Any = uvicorn.Config(app, host=host, port=port, log_level=log_level.lower())
    uvicorn.Server(config).run()
