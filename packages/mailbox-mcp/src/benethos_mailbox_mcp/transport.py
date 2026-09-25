"""The MCP server over HTTP (streamable HTTP), behind a bearer guard.

The only module that imports ``uvicorn``. The SDK's own runner builds the
app and starts uvicorn in one step, which leaves nowhere to put the guard,
so the app is built here, wrapped, and served.

The guard admits callers with one shared token, ``MAILBOX_MCP_BEARER_TOKEN``.
It is not passed on: the server calls the REST API with its own
``MAILBOX_SERVICE_TOKEN``, whose user decides which tools exist.
"""

from __future__ import annotations

import hmac
import logging
import os
from typing import Any

from mcp.server.mcpserver import MCPServer
from mcp.server.transport_security import TransportSecuritySettings
from starlette.types import ASGIApp, Receive, Scope, Send

logger = logging.getLogger(__name__)

ENV_VAR = "MAILBOX_MCP_BEARER_TOKEN"

# The error envelope of the REST API.
_REFUSED = b'{"error":{"code":"unauthorized","message":"bearer token required"}}'

# Binds only this machine can reach.
LOCALHOST_BINDS = frozenset({"127.0.0.1", "localhost", "::1", ""})


def token_from_env() -> str | None:
    """The bearer token. Unset or blank means no guard."""
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
        # The scheme is case-insensitive (RFC 7235) and no secret. Only the
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
    """Host and Origin checks against DNS rebinding. An explicit list wins.
    A loopback bind admits the loopback names. Any other bind without a list
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


def serve_stdio(server: MCPServer) -> None:
    """Over the client's own pipes: no port, so no token."""
    if token_from_env() is not None:
        logger.warning(
            "%s is set, but stdio has no port anyone could reach: the "
            "client owns this process, so the token is ignored",
            ENV_VAR,
        )
    logger.info("Starting Mailbox MCP server (stdio)")
    server.run(transport="stdio")


def serve_http(
    server: MCPServer,
    *,
    host: str,
    port: int,
    path: str,
    allowed_hosts: list[str],
    allowed_origins: list[str],
    log_level: str,
) -> None:
    """Over streamable HTTP, behind the bearer guard where a token is set."""
    token = token_from_env()
    logger.info(
        "Starting Mailbox MCP server (streamable HTTP) on http://%s:%s%s",
        host,
        port,
        path,
    )
    if token is None:
        logger.warning(
            "No %s set: anything that can reach %s:%s can use every tool of "
            "this server's user. Fine for a loopback bind on your own "
            "machine, not anywhere else.",
            ENV_VAR,
            host,
            port,
        )
    else:
        logger.info("Bearer token required: requests without it get HTTP 401.")
    app = http_app(
        server,
        path=path,
        host=host,
        security=transport_security(host, allowed_hosts, allowed_origins),
        token=token,
    )
    run_http(app, host=host, port=port, log_level=log_level)
