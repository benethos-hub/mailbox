"""``backup FILE`` writes an encrypted backup, in format 2 or with
``--format 3``, ``backup verify FILE`` checks one of any format."""

from __future__ import annotations

import argparse
from pathlib import Path

from benethos_mailbox_common.log import lines

from .. import __version__
from ..common.clock import parse_iso
from ..config import load_settings
from .common import (
    STORED,
    Commands,
    UsageError,
    master_key,
    read_recovery_key,
    say,
    stored,
)


def add(commands: Commands, option: argparse.ArgumentParser) -> None:
    backup = commands.add_parser(
        "backup",
        help="write an encrypted backup: `backup FILE`, or check one: "
        "`backup verify FILE`",
        parents=[option],
    )
    backup.add_argument("target", nargs="+", metavar="[verify] FILE")
    backup.add_argument(
        "--format",
        type=int,
        choices=(2, 3),
        help="with FILE: 2, the file of the database (the default on "
        "SQLite), or 3, the export of its records (the default, and the "
        "only one, on PostgreSQL)",
    )
    backup.add_argument(
        "--recovery-key",
        action="store_true",
        help="with verify: ask for the recovery key at a hidden prompt, or "
        "read it from stdin when piped",
    )


def run(args: argparse.Namespace) -> None:
    if args.target[0] == "verify":
        if args.format is not None:
            # The format of a backup is read from the file itself.
            raise UsageError("--format goes with `backup FILE`")
        _verify(args.target, args.recovery_key, args.env_file)
    elif args.recovery_key:
        # A backup is written with the master key the service holds.
        raise UsageError("--recovery-key goes with `backup verify FILE`")
    else:
        _write(args.target, args.env_file, args.format)


def _verify(target: list[str], recovery_key: bool, env_file: Path | None) -> None:
    from ..data.backup import verify_backup, verify_in_memory

    if len(target) != 2:
        raise UsageError("use `backup verify FILE`")
    settings = load_settings(env_file)
    master = read_recovery_key() if recovery_key else master_key(settings)
    if settings.on_server:
        # No file beside a database on a server: nothing on a disk.
        manifest = verify_in_memory(Path(target[1]), master)
    else:
        # Decrypted beside the database, where it is as safe as that is.
        database = settings.database_path
        scratch = database.with_name(database.name + ".verifying")
        manifest = verify_backup(Path(target[1]), master, scratch)
    say(
        f"OK: backup of {lines.log_time(parse_iso(manifest.created_at))}, format "
        f"{manifest.format}, service {manifest.service_version}, schema "
        f"{manifest.schema_version}"
    )


def _write(target: list[str], env_file: Path | None, chosen: int | None) -> None:
    from ..assembly import opened
    from ..data.backup import create_backup
    from ..domain.activity import HOST, system

    if len(target) != 1:
        raise UsageError("use `backup FILE` or `backup verify FILE`")
    settings = stored(load_settings(env_file), "backups")
    format = _format(settings.on_server, chosen)
    with opened(settings) as services:
        if services.store is None:
            raise UsageError(f"backups need {STORED}")
        manifest = create_backup(
            services.store,
            services.vault.master_key(),
            Path(target[0]),
            __version__,
            format=format,
        )
        services.activity.record(
            system.BackupWritten(
                by=HOST,
                file=target[0],
                schema=manifest.schema_version,
                format=manifest.format,
            )
        )
    say(
        f"Backup written in format {manifest.format}: schema "
        f"{manifest.schema_version}, "
        f"{lines.log_time(parse_iso(manifest.created_at))}. "
        "It opens only with this master key or the recovery key."
    )


def _format(on_server: bool, chosen: int | None) -> int:
    """The format of a backup: 2 by default on SQLite, 3 on a database
    server, which has no file for format 2."""
    if not on_server:
        return chosen or 2
    if chosen == 2:
        raise UsageError(
            "format 2 is the file of a SQLite database: a database on"
            " PostgreSQL is backed up in format 3"
        )
    return 3
