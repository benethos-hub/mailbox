"""The command line of the MCP server: its options over the settings
(``config``), the log, and the start over stdio or streamable HTTP.
The tools and what the token may do are ``server``'s."""

from __future__ import annotations

import argparse
import logging
import sys
from pathlib import Path
from typing import get_args

import anyio
from pydantic import ValidationError

from benethos_mailbox_common.log import lines, redact

from . import __version__, config, server, tools, transport
from .client import Connect, Environment, connector, from_environment
from .errors import MailboxError, ToolError

logger = logging.getLogger(__name__)


async def _at_start(connect: Connect) -> set[str]:
    """What the token may do, asked before the server runs. Its client
    belongs to this event loop, which ends here: the server makes its own
    in its lifespan."""
    async with connect() as made:
        with tools.calling(made):
            return await server.allowed_operations()


TRANSPORTS = get_args(config.Transport)
LOG_LEVELS = get_args(config.LogLevel)


def _build_parser() -> argparse.ArgumentParser:
    """Options on the command line win over ``MAILBOX_MCP_*`` in the
    environment, which win over the settings file, which wins over the
    defaults of ``config.Settings``. The bearer token has no option: an
    argument shows in the process list."""
    parser = argparse.ArgumentParser(prog="benethos-mailbox-mcp")
    parser.add_argument("--version", action="version", version=__version__)
    parser.add_argument(
        "--env-file",
        type=Path,
        metavar="PATH",
        help=f"the settings file, else {config.ENV_FILE_VARIABLE}, else "
        f"{config.ENV_FILE} if it exists, else .env in the config folder of "
        "the operating system. The environment wins over it.",
    )
    # No defaults here: an option not given leaves its setting to the
    # environment, the file and config.Settings.
    parser.add_argument("--transport", choices=TRANSPORTS)
    parser.add_argument("--host")
    parser.add_argument("--port", type=int)
    parser.add_argument("--path")
    parser.add_argument(
        "--allowed-hosts",
        help="comma-separated Host values, e.g. mcp.example.org:443",
    )
    parser.add_argument("--allowed-origins", help="comma-separated Origin values")
    parser.add_argument("--log-level", type=str.upper, choices=LOG_LEVELS)
    return parser


def _settings(
    parser: argparse.ArgumentParser, args: argparse.Namespace, found: Path | None
) -> config.Settings:
    """The settings, the options first. A wrong value is refused as
    argparse refuses an option, with the setting's name. A token's value
    is never shown."""
    try:
        return config.load_settings(
            found,
            transport=args.transport,
            host=args.host,
            port=args.port,
            path=args.path,
            allowed_hosts=args.allowed_hosts,
            allowed_origins=args.allowed_origins,
            log_level=args.log_level,
        )
    except ValidationError as exc:
        problems = []
        for error in exc.errors():
            name = config.variable(str(error["loc"][0]))
            shown = "" if "TOKEN" in name else f", not {error['input']!r}"
            problems.append(f"{name}: {error['msg']}{shown}")
        parser.error("; ".join(problems))


def _service(settings: config.Settings) -> Environment:
    """The service as the settings name it. Without an address, the
    client's default."""
    token = settings.service_token
    return Environment(
        url=(settings.service_url or from_environment().url).rstrip("/"),
        token=token.get_secret_value() if token else "",
        allow_http=settings.service_allow_http,
    )


def _csv(value: str) -> list[str]:
    return [item.strip() for item in value.split(",") if item.strip()]


def configure_logging(level: str) -> None:
    """The lines of the service's log (``benethos_mailbox_common.log.lines``):
    short and in colour on a terminal, else plain, a noted secret masked."""
    # stderr only: on stdio, stdout carries the JSON-RPC stream.
    package = __name__.rpartition(".")[0]
    logging.basicConfig(level=level, handlers=[lines.stderr_handler(package)])
    # httpx names every request with its URL at INFO, and a URL carries
    # search terms and message ids. The MCP library names each request.
    # The client keeps this log in its files.
    for name in ("httpx", "httpcore", "mcp"):
        logging.getLogger(name).setLevel(logging.WARNING)


def main(argv: list[str] | None = None) -> None:
    parser = _build_parser()
    args = parser.parse_args(argv)
    try:
        found = config.settings_file(args.env_file)
    except FileNotFoundError as exc:
        sys.exit(f"benethos-mailbox-mcp: {exc}")
    settings = _settings(parser, args, found)
    configure_logging(settings.log_level)
    if found is not None:
        logger.info("Settings from %s", found)
    environment = _service(settings)
    bearer = settings.bearer_token
    token = bearer.get_secret_value() if bearer else None
    # No line names either token. Noted, a slip still writes ***.
    for secret in (environment.token, token):
        if secret:
            redact.note(secret)
    connect = connector(environment)
    try:
        operations = anyio.run(_at_start, connect)
    except (MailboxError, ToolError) as exc:
        sys.exit(f"benethos-mailbox-mcp: {exc}")
    built = server.build_server(operations, connect)
    server.started(operations, settings.transport, environment.url)
    if settings.transport == "stdio":
        transport.serve_stdio(built, token)
        return
    transport.serve_http(
        built,
        host=settings.host,
        port=settings.port,
        path=settings.path,
        allowed_hosts=_csv(settings.allowed_hosts),
        allowed_origins=_csv(settings.allowed_origins),
        log_level=settings.log_level,
        token=token,
    )
