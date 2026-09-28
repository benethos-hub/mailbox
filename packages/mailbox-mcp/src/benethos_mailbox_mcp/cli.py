"""The command line of the MCP server: its options, the environment
``MAILBOX_MCP_*``, the log, and the start over stdio or streamable HTTP.
The tools and what the token may do are ``server``'s."""

from __future__ import annotations

import argparse
import logging
import os
import sys

import anyio

from . import __version__, server, transport
from .errors import ToolError


async def _at_start() -> set[str]:
    """What the token may do, asked before the server runs. Its connections
    belong to this event loop, which ends here: the server's own loop gets a
    fresh client."""
    try:
        return await server.allowed_operations()
    finally:
        left = server.use_client(None)
        if left is not None:
            await left.aclose()


TRANSPORTS = ("stdio", "streamable-http")
LOG_LEVELS = ("DEBUG", "INFO", "WARNING", "ERROR")


def _env(name: str, default: str) -> str:
    return os.environ.get(f"MAILBOX_MCP_{name}") or default


def _build_parser() -> argparse.ArgumentParser:
    """Options on the command line win over ``MAILBOX_MCP_*`` in the
    environment, which win over the defaults. The bearer token has no option:
    an argument shows in the process list."""
    parser = argparse.ArgumentParser(prog="benethos-mailbox-mcp")
    parser.add_argument("--version", action="version", version=__version__)
    parser.add_argument(
        "--transport", choices=TRANSPORTS, default=_env("TRANSPORT", "stdio")
    )
    parser.add_argument("--host", default=_env("HOST", "127.0.0.1"))
    # A default given as text passes through type, so a bad port from the
    # environment is refused like one on the command line.
    parser.add_argument("--port", type=int, default=_env("PORT", "8000"))
    parser.add_argument("--path", default=_env("PATH", "/mcp"))
    parser.add_argument(
        "--allowed-hosts",
        default=_env("ALLOWED_HOSTS", ""),
        help="comma-separated Host values, e.g. mcp.example.org:443",
    )
    parser.add_argument(
        "--allowed-origins",
        default=_env("ALLOWED_ORIGINS", ""),
        help="comma-separated Origin values",
    )
    parser.add_argument(
        "--log-level",
        default=_env("LOG_LEVEL", "INFO"),
        type=str.upper,
        choices=LOG_LEVELS,
    )
    return parser


def _check_environment(
    parser: argparse.ArgumentParser, args: argparse.Namespace
) -> None:
    """argparse checks choices on the command line only, not a default
    read from the environment."""
    for name, value, allowed in (
        ("TRANSPORT", args.transport, TRANSPORTS),
        ("LOG_LEVEL", args.log_level, LOG_LEVELS),
    ):
        if value not in allowed:
            parser.error(
                f"MAILBOX_MCP_{name} must be one of {', '.join(allowed)}, not {value!r}"
            )


def _csv(value: str) -> list[str]:
    return [item.strip() for item in value.split(",") if item.strip()]


def configure_logging(level: str) -> None:
    # stderr only: on stdio, stdout carries the JSON-RPC stream.
    logging.basicConfig(level=level, stream=sys.stderr)
    # httpx names every request with its URL at INFO, and a URL carries
    # search terms and message ids. The MCP library names each request.
    # The client keeps this log in its files.
    for name in ("httpx", "httpcore", "mcp"):
        logging.getLogger(name).setLevel(logging.WARNING)


def main(argv: list[str] | None = None) -> None:
    parser = _build_parser()
    args = parser.parse_args(argv)
    _check_environment(parser, args)
    configure_logging(args.log_level)
    try:
        operations = anyio.run(_at_start)
    except ToolError as exc:
        sys.exit(f"benethos-mailbox-mcp: {exc}")
    built = server.build_server(operations)
    server.started(operations, args.transport)
    if args.transport == "stdio":
        transport.serve_stdio(built)
        return
    transport.serve_http(
        built,
        host=args.host,
        port=args.port,
        path=args.path,
        allowed_hosts=_csv(args.allowed_hosts),
        allowed_origins=_csv(args.allowed_origins),
        log_level=args.log_level,
    )
