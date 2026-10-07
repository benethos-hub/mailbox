"""``backup FILE`` writes an encrypted backup, ``backup verify FILE``
checks one."""

from __future__ import annotations

import argparse
from pathlib import Path

from .. import __version__
from ..common.clock import log_time, parse_iso
from ..config import load_settings
from .common import (
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
        "--recovery-key",
        action="store_true",
        help="with verify: read the recovery key from stdin",
    )


def run(args: argparse.Namespace) -> None:
    if args.target[0] == "verify":
        _verify(args.target, args.recovery_key, args.env_file)
    elif args.recovery_key:
        # A backup is written with the master key the service holds.
        raise UsageError("--recovery-key goes with `backup verify FILE`")
    else:
        _write(args.target, args.env_file)


def _verify(target: list[str], recovery_key: bool, env_file: Path | None) -> None:
    from ..data.backup import verify_backup

    if len(target) != 2:
        raise UsageError("use `backup verify FILE`")
    settings = load_settings(env_file)
    master = read_recovery_key() if recovery_key else master_key(settings)
    # Decrypted beside the database, where it is as safe as that is.
    database = settings.database_path
    scratch = database.with_name(database.name + ".verifying")
    manifest = verify_backup(Path(target[1]), master, scratch)
    say(
        f"OK: backup of {log_time(parse_iso(manifest.created_at))}, service "
        f"{manifest.service_version}, schema {manifest.schema_version}"
    )


def _write(target: list[str], env_file: Path | None) -> None:
    from ..assembly import opened
    from ..data.backup import create_backup
    from ..domain.activity import HOST, system

    if len(target) != 1:
        raise UsageError("use `backup FILE` or `backup verify FILE`")
    settings = stored(load_settings(env_file), "backups")
    with opened(settings) as services:
        if services.store is None:
            raise UsageError("backups need MAILBOX_SERVICE_STORAGE=sqlite")
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
    say(
        f"Backup written: schema {manifest.schema_version}, "
        f"{log_time(parse_iso(manifest.created_at))}. "
        "It opens only with this master key or the recovery key."
    )
