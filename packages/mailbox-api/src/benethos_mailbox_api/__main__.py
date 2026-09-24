"""Command line entry point: ``benethos-mailbox-api serve``."""

from __future__ import annotations

import argparse
import sys

from . import __version__
from .config import Settings


def main(argv: list[str] | None = None) -> int:
    parser = argparse.ArgumentParser(prog="benethos-mailbox-api")
    parser.add_argument("--version", action="version", version=__version__)
    commands = parser.add_subparsers(dest="command", required=True)
    serve = commands.add_parser("serve", help="run the REST API")
    serve.add_argument("--host")
    serve.add_argument("--port", type=int)
    commands.add_parser("openapi", help="print the OpenAPI document as JSON")
    args = parser.parse_args(argv)

    if args.command == "openapi":
        from .main import openapi_json

        sys.stdout.write(openapi_json())
    elif args.command == "serve":  # pragma: no branch
        import uvicorn

        from .main import create_app

        settings = Settings()
        uvicorn.run(
            create_app(settings),
            host=args.host or settings.host,
            port=args.port or settings.port,
            log_level=settings.log_level.lower(),
        )
    return 0


if __name__ == "__main__":
    sys.exit(main())
