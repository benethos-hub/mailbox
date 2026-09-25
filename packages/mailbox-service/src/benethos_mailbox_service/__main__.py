"""Command line entry point: ``benethos-mailbox-service serve`` and the host tools."""

from __future__ import annotations

import argparse
import getpass
import sys
from pathlib import Path

from . import __version__
from .config import Settings


def main(argv: list[str] | None = None) -> int:
    parser = _parser()
    args = parser.parse_args(argv)
    try:
        return _run(args)
    except _EXPECTED as exc:
        print(f"error: {_message(exc)}", file=sys.stderr)
        return 1


def _parser() -> argparse.ArgumentParser:
    parser = argparse.ArgumentParser(prog="benethos-mailbox-service")
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
    keys_commands.add_parser(
        "generate",
        help="print a new master key for a key file or container secret; "
        "stores nothing",
    )

    backup = commands.add_parser(
        "backup",
        help="write an encrypted backup: `backup FILE`, or check one: "
        "`backup verify FILE`",
    )
    backup.add_argument("target", nargs="+", metavar="[verify] FILE")
    backup.add_argument(
        "--recovery-key",
        action="store_true",
        help="with verify: read the recovery key from stdin",
    )

    restore = commands.add_parser(
        "restore", help="replace the database with a backup; stop the service first"
    )
    restore.add_argument("source", type=Path)
    restore.add_argument(
        "--recovery-key",
        action="store_true",
        help="read the recovery key from stdin and store it in the key provider",
    )
    return parser


def _run(args: argparse.Namespace) -> int:
    if args.command == "openapi":
        from .main import openapi_json

        sys.stdout.write(openapi_json())
    elif args.command == "users":
        _create_admin(args.name)
    elif args.command == "keys":
        _keys(args.keys_command)
    elif args.command == "backup":
        _backup(args.target, args.recovery_key)
    elif args.command == "restore":
        _restore(args.source, args.recovery_key)
    elif args.command == "serve":  # pragma: no branch
        import uvicorn

        from .main import create_app

        settings = Settings()
        if settings.storage == "sqlite":
            print(f"database: {settings.database_path}", file=sys.stderr)
        else:
            print("storage: memory, nothing is kept", file=sys.stderr)
        uvicorn.run(
            create_app(settings),
            host=args.host or settings.host,
            port=args.port or settings.port,
            log_level=settings.log_level.lower(),
        )
    return 0


def _create_admin(name: str) -> None:
    from .main import opened

    settings = Settings()
    with opened(settings) as services:
        user, token = services.users.create_admin(name)
    print(
        f"Created user {user.id} ({user.name}) with every right in "
        f"{settings.database_path}. Its token is shown this once:",
        file=sys.stderr,
    )
    print(token)


def _keys(command: str) -> None:
    if command == "generate":
        from .data.secrets import cipher, encode_recovery

        print(encode_recovery(cipher.new_key()))
        return
    from .main import opened

    with opened(Settings()) as services:
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
            services.vault.import_master_key(_read_recovery_key())
            print("Master key stored.", file=sys.stderr)


def _backup(target: list[str], recovery_key: bool) -> None:
    from .data.secrets.backup import create_backup, read_backup
    from .main import opened

    if target[0] == "verify" and len(target) == 2:
        master = _read_recovery_key() if recovery_key else _master_key()
        manifest, _ = read_backup(Path(target[1]), master)
        print(
            f"OK: backup of {manifest.created_at}, service "
            f"{manifest.service_version}, schema {manifest.schema_version}",
            file=sys.stderr,
        )
        return
    if len(target) != 1:
        raise _UsageError("use `backup FILE` or `backup verify FILE`")
    settings = Settings()
    if settings.storage != "sqlite":
        raise _UsageError("backups need MAILBOX_SERVICE_STORAGE=sqlite")
    with opened(settings) as services:
        assert services.database is not None
        manifest = create_backup(
            services.database,
            services.vault.master_key(),
            Path(target[0]),
            __version__,
        )
    print(
        f"Backup written: schema {manifest.schema_version}, {manifest.created_at}. "
        "It opens only with this master key or the recovery key.",
        file=sys.stderr,
    )


def _restore(source: Path, recovery_key: bool) -> None:
    from .data.secrets.backup import restore_backup
    from .main import key_provider, opened

    settings = Settings()
    master = _read_recovery_key() if recovery_key else _master_key()
    manifest = restore_backup(source, master, settings.database_path)
    if recovery_key and key_provider(settings).load() != master:
        with opened(settings) as services:
            services.vault.import_master_key(master)
    print(
        f"Restored the backup of {manifest.created_at}. The previous database "
        "was kept beside it. Accounts whose OAuth tokens changed since then "
        "need reconnecting.",
        file=sys.stderr,
    )


def _master_key() -> bytes:
    from .main import key_provider

    provider = key_provider(Settings())
    key = provider.load()
    if key is None:
        raise _UsageError(
            f"no master key in {provider.describe()}: pass --recovery-key"
        )
    return key


def _read_recovery_key() -> bytes:
    from .data.secrets import decode_recovery

    text = (
        getpass.getpass("Recovery key: ")
        if sys.stdin.isatty()
        else sys.stdin.readline()
    )
    return decode_recovery(text)


class _UsageError(Exception):
    pass


def _expected() -> tuple[type[BaseException], ...]:
    """What a command reports as an error and a return code, not a trace:
    its own usage, a key or backup that cannot be read, the service's
    errors, and settings that do not validate."""
    from pydantic import ValidationError

    from .data.secrets import KeyProviderError
    from .data.secrets.backup import BackupError
    from .errors import MailboxServiceError

    return (
        _UsageError,
        BackupError,
        KeyProviderError,
        MailboxServiceError,
        ValidationError,
    )


def _message(exc: BaseException) -> str:
    message = getattr(exc, "message", None)
    return str(message or exc)


_EXPECTED = _expected()


if __name__ == "__main__":
    sys.exit(main())
