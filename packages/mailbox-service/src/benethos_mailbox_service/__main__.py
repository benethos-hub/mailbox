"""Command line entry point: ``benethos-mailbox-service serve`` and the host tools."""

from __future__ import annotations

import argparse
import getpass
import sys
from pathlib import Path

from . import __version__
from .config import ENV_FILE, Settings, load_settings, settings_file


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
    parser.add_argument(
        "--env-file", type=Path, default=None, metavar="PATH", help=_ENV_FILE_HELP
    )
    # The same option after a command. Given there, it wins.
    option = argparse.ArgumentParser(add_help=False)
    option.add_argument(
        "--env-file",
        type=Path,
        default=argparse.SUPPRESS,
        metavar="PATH",
        help=_ENV_FILE_HELP,
    )
    commands = parser.add_subparsers(dest="command", required=True)
    serve = commands.add_parser("serve", help="run the REST API", parents=[option])
    serve.add_argument("--host")
    serve.add_argument("--port", type=int)
    commands.add_parser("openapi", help="print the OpenAPI document as JSON")

    users = commands.add_parser(
        "users", help="manage users on this host", parents=[option]
    )
    users_commands = users.add_subparsers(dest="users_command", required=True)
    create_admin = users_commands.add_parser(
        "create-admin",
        help="create a user with every right and print a one-time password",
        parents=[option],
    )
    create_admin.add_argument("--name", default="admin")
    set_password = users_commands.add_parser(
        "set-password",
        help="give a user a new one-time password and print it, "
        "e.g. when the last administrator forgot theirs",
        parents=[option],
    )
    set_password.add_argument("name")

    keys = commands.add_parser(
        "keys", help="the master key and the data key", parents=[option]
    )
    keys_commands = keys.add_subparsers(dest="keys_command", required=True)
    keys_commands.add_parser(
        "init",
        help="create the keys and print the recovery key once",
        parents=[option],
    )
    keys_commands.add_parser(
        "import",
        help="store the master key from a recovery key, read from stdin",
        parents=[option],
    )
    keys_commands.add_parser(
        "generate",
        help="print a new master key for a key file or container secret. "
        "Stores nothing.",
    )

    backup = commands.add_parser(
        "backup",
        help="write an encrypted backup: `backup FILE`, or check one: "
        "`backup verify FILE`",
        parents=[option],
    )
    backup.add_argument("target", nargs="+", metavar="[verify] FILE")
    backup.add_argument(
        "--recovery-key",
        action="store_true",
        help="with verify: read the recovery key from stdin",
    )

    restore = commands.add_parser(
        "restore",
        help="replace the database with a backup. Stop the service first.",
        parents=[option],
    )
    restore.add_argument("source", type=Path)
    restore.add_argument(
        "--recovery-key",
        action="store_true",
        help="read the recovery key from stdin and store it in the key provider",
    )
    restore.add_argument(
        "--replace-master-key",
        action="store_true",
        help="with --recovery-key: overwrite another master key the key "
        "provider holds. The database it opens is lost without its recovery key.",
    )
    return parser


_ENV_FILE_HELP = (
    f"the settings file, else MAILBOX_SERVICE_ENV_FILE, else {ENV_FILE} if it "
    "exists. Relative paths in a file named here count from its folder."
)


def _run(args: argparse.Namespace) -> int:
    if args.command == "openapi":
        from .main import openapi_json

        sys.stdout.write(openapi_json())
    elif args.command == "users":
        _users(args)
    elif args.command == "keys":
        _keys(args.keys_command, args.env_file)
    elif args.command == "backup":
        _backup(args.target, args.recovery_key, args.env_file)
    elif args.command == "restore":
        _restore(args.source, args.recovery_key, args.replace_master_key, args.env_file)
    elif args.command == "serve":  # pragma: no branch
        import logging.config

        import uvicorn

        from .data.logbook import LogBook
        from .logs import log_config, short_source
        from .main import create_app

        settings = load_settings(args.env_file)
        # Before the app is built: building it may warn already.
        # The log page names a source as the console does.
        book = LogBook(source=short_source)
        config = log_config(settings.log_level, book)
        logging.config.dictConfig(config)
        # The log names the settings and the database once the app starts.
        app = create_app(
            settings, logbook=book, settings_file=settings_file(args.env_file)
        )
        uvicorn.run(
            app,
            host=args.host or settings.host,
            port=args.port or settings.port,
            log_config=config,
            log_level=settings.log_level,
            forwarded_allow_ips=settings.forwarded_allow_ips,
        )
    return 0


def _users(args: argparse.Namespace) -> None:
    """The password alone goes to stdout, so it can be piped on."""
    import anyio

    from .main import opened

    settings = _stored(load_settings(args.env_file), "users")
    with opened(settings) as services:
        if args.users_command == "create-admin":
            user, password = anyio.run(services.users.create_admin, args.name)
            done = f"Created user {user.id} ({user.name}) with every right"
        else:
            before = services.auth.user_named(args.name)
            user, password = anyio.run(services.users.reset_password, args.name)
            done = f"Gave {user.name} ({user.id}) a new password"
            if before is not None and not before.ui_sign_in:
                done += ", and its UI sign-in, which was off,"
    print(
        f"{done} in {settings.database_path}. Sign in to the UI with this "
        "one-time password, shown this once. The UI then asks for one of "
        "your own:",
        file=sys.stderr,
    )
    print(password)


def _keys(command: str, env_file: Path | None) -> None:
    if command == "generate":
        from .data.secrets import cipher, encode_recovery

        print(encode_recovery(cipher.new_key()))
        return
    from .domain.activity import HOST, system
    from .main import opened

    with opened(_stored(load_settings(env_file), "keys")) as services:
        if command == "init":
            recovery = services.vault.initialize()
            services.activity.record(system.KeysCreated(by=HOST))
            print(
                "Keys created. The recovery key below is shown this once. Keep it "
                "apart from any backup: without it, a backup cannot be restored "
                "on another machine.",
                file=sys.stderr,
            )
            print(recovery)
        else:
            services.vault.import_master_key(_read_recovery_key())
            services.activity.record(system.MasterKeyStored(by=HOST))
            print("Master key stored.", file=sys.stderr)


def _backup(target: list[str], recovery_key: bool, env_file: Path | None) -> None:
    from .data.backup import create_backup, read_backup
    from .domain.activity import HOST, system
    from .main import opened

    if target[0] == "verify":
        if len(target) != 2:
            raise _UsageError("use `backup verify FILE`")
        master = (
            _read_recovery_key()
            if recovery_key
            else _master_key(load_settings(env_file))
        )
        manifest, _ = read_backup(Path(target[1]), master)
        print(
            f"OK: backup of {manifest.created_at}, service "
            f"{manifest.service_version}, schema {manifest.schema_version}",
            file=sys.stderr,
        )
        return
    if len(target) != 1:
        raise _UsageError("use `backup FILE` or `backup verify FILE`")
    settings = _stored(load_settings(env_file), "backups")
    with opened(settings) as services:
        assert services.store is not None
        manifest = create_backup(
            services.store,
            services.vault.master_key(),
            Path(target[0]),
            __version__,
        )
        services.activity.record(
            system.BackupWritten(
                by=HOST, file=target[0], schema=manifest.schema_version
            )
        )
    print(
        f"Backup written: schema {manifest.schema_version}, {manifest.created_at}. "
        "It opens only with this master key or the recovery key.",
        file=sys.stderr,
    )


def _restore(
    source: Path, recovery_key: bool, replace_master_key: bool, env_file: Path | None
) -> None:
    from .data.backup import restore_backup
    from .domain.activity import HOST, ActivityLog, system
    from .main import key_provider, opened

    if replace_master_key and not recovery_key:
        raise _UsageError("--replace-master-key goes with --recovery-key")
    settings = load_settings(env_file)
    master = _read_recovery_key() if recovery_key else _master_key(settings)
    provider = key_provider(settings)
    held = provider.load() if recovery_key else master
    if held is not None and held != master and not replace_master_key:
        # Checked before the restore: afterwards the kept database would
        # open with the key held now alone.
        raise _UsageError(
            f"{provider.describe()} holds another master key. The database it "
            "opens now would be lost with it: note its recovery key, then pass "
            "--replace-master-key"
        )
    manifest = restore_backup(source, master, settings.database_path)
    if held != master:
        with opened(settings) as services:
            services.vault.import_master_key(master, replace=replace_master_key)
    ActivityLog().record(
        system.BackupRestored(
            by=HOST,
            file=str(source),
            schema=manifest.schema_version,
            made=str(manifest.created_at),
        )
    )
    print(
        f"Restored the backup of {manifest.created_at}. The previous database "
        "was kept beside it. Accounts whose OAuth tokens changed since then "
        "need reconnecting.",
        file=sys.stderr,
    )


def _stored(settings: Settings, what: str) -> Settings:
    """``settings``, if they keep what the command writes: in memory it
    would vanish with the command."""
    if settings.storage != "sqlite":
        raise _UsageError(f"{what} need MAILBOX_SERVICE_STORAGE=sqlite")
    return settings


def _master_key(settings: Settings) -> bytes:
    from .main import key_provider

    provider = key_provider(settings)
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

    from .data.backup import BackupError
    from .data.secrets import KeyProviderError
    from .errors import MailboxServiceError

    return (
        _UsageError,
        BackupError,
        KeyProviderError,
        MailboxServiceError,
        ValidationError,
        # The last net: a file the host does not let the service read or
        # write, e.g. the OAuth client secret.
        OSError,
    )


def _message(exc: BaseException) -> str:
    message = getattr(exc, "message", None)
    return str(message or exc)


_EXPECTED = _expected()


if __name__ == "__main__":
    sys.exit(main())
