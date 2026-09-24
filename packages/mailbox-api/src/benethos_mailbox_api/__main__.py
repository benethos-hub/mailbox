"""Command line entry point: ``benethos-mailbox-api serve``."""

from __future__ import annotations

import argparse
import getpass
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
    users = commands.add_parser("users", help="manage users on this host")
    users_commands = users.add_subparsers(dest="users_command", required=True)
    create_admin = users_commands.add_parser(
        "create-admin", help="create a user with every right and print its token"
    )
    create_admin.add_argument("--name", default="admin")
    keys = commands.add_parser("keys", help="the master key and the data key")
    keys_commands = keys.add_subparsers(dest="keys_command", required=True)
    keys_commands.add_parser(
        "init", help="create the keys and print the recovery key once"
    )
    keys_commands.add_parser(
        "import", help="store the master key from a recovery key, read from stdin"
    )
    args = parser.parse_args(argv)

    if args.command == "openapi":
        from .main import openapi_json

        sys.stdout.write(openapi_json())
    elif args.command == "users":
        from .main import build_services

        settings = Settings()
        services = build_services(settings)
        try:
            user, token = services.users.create_admin(args.name)
        finally:
            services.close()
        print(
            f"Created user {user.id} ({user.name}) with every right in "
            f"{settings.database_path}. Its token is shown this once:",
            file=sys.stderr,
        )
        print(token)
    elif args.command == "keys":
        return _keys(args.keys_command)
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


def _keys(command: str) -> int:
    from .data.secrets import decode_recovery
    from .main import build_services

    settings = Settings()
    services = build_services(settings)
    try:
        if command == "init":
            recovery = services.vault.initialize()
            print(
                "Keys created. The recovery key below is shown this once. Keep it "
                "apart from any backup: without it, a backup cannot be restored "
                "on another machine.",
                file=sys.stderr,
            )
            print(recovery)
        else:
            text = (
                getpass.getpass("Recovery key: ")
                if sys.stdin.isatty()
                else sys.stdin.readline()
            )
            services.vault.import_master_key(decode_recovery(text))
            print("Master key stored.", file=sys.stderr)
    finally:
        services.close()
    return 0


if __name__ == "__main__":
    sys.exit(main())
