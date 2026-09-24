"""The MCP server: thin tools over the REST client."""

from __future__ import annotations

import argparse
import logging
from typing import Any

from mcp.server.mcpserver import MCPServer

from . import __version__
from .client import MailboxApiClient

logger = logging.getLogger(__name__)

_INSTRUCTIONS = """\
Mail across several connected accounts. Call list_accounts first to learn the
account ids the other tools take.
"""

mcp = MCPServer(
    name="benethos-mailbox-mcp",
    title="Mailbox MCP Server",
    version=__version__,
    instructions=_INSTRUCTIONS,
)

_client: MailboxApiClient | None = None


def client() -> MailboxApiClient:
    """The shared REST client, created on first use."""
    global _client
    if _client is None:
        _client = MailboxApiClient()
    return _client


@mcp.tool()
async def list_accounts() -> list[dict[str, Any]]:
    """List the connected mail accounts with id, address, provider and status.

    Other tools take the account id. An account with status needs_reauth has
    to be reconnected in the Mailbox API service before it answers again.
    """
    return await client().list_accounts()


def _build_parser() -> argparse.ArgumentParser:
    parser = argparse.ArgumentParser(prog="benethos-mailbox-mcp")
    parser.add_argument("--version", action="version", version=__version__)
    parser.add_argument(
        "--transport", choices=["stdio", "streamable-http"], default="stdio"
    )
    # The service takes 8080, so the MCP server defaults to the port beside it.
    parser.add_argument("--host", default="127.0.0.1")
    parser.add_argument("--port", type=int, default=8081)
    parser.add_argument("--log-level", default="INFO")
    return parser


def main(argv: list[str] | None = None) -> None:
    args = _build_parser().parse_args(argv)
    # stderr only: on stdio, stdout carries the JSON-RPC stream.
    logging.basicConfig(level=args.log_level)
    logger.info("Starting Mailbox MCP server (%s)", args.transport)
    if args.transport == "stdio":
        mcp.run(transport="stdio")
    else:
        # No bearer guard yet: bind to loopback only until phase 3 adds one.
        mcp.run(transport="streamable-http", host=args.host, port=args.port)
