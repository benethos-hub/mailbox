"""``restore FILE``: the database replaced with a backup, the previous
one kept beside it."""

from __future__ import annotations

import argparse
import sys
from pathlib import Path

from ..config import load_settings
from .common import Commands, UsageError, master_key, read_recovery_key


def add(commands: Commands, option: argparse.ArgumentParser) -> None:
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


def run(args: argparse.Namespace) -> None:
    from ..assembly import key_provider, opened
    from ..data.backup import restore_backup
    from ..domain.activity import HOST, ActivityLog, system

    if args.replace_master_key and not args.recovery_key:
        raise UsageError("--replace-master-key goes with --recovery-key")
    settings = load_settings(args.env_file)
    master = read_recovery_key() if args.recovery_key else master_key(settings)
    provider = key_provider(settings)
    held = provider.load() if args.recovery_key else master
    if held is not None and held != master and not args.replace_master_key:
        # Checked before the restore: afterwards the kept database would
        # open with the key held now alone.
        raise UsageError(
            f"{provider.describe()} holds another master key. The database it "
            "opens now would be lost with it: note its recovery key, then pass "
            "--replace-master-key"
        )
    manifest = restore_backup(args.source, master, settings.database_path)
    if held != master:
        with opened(settings) as services:
            services.vault.import_master_key(master, replace=args.replace_master_key)
    ActivityLog().record(
        system.BackupRestored(
            by=HOST,
            file=str(args.source),
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
