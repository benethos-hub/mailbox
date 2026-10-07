"""``keys init``, ``keys import`` and ``keys generate``: the master key
and the data key."""

from __future__ import annotations

import argparse

from ..config import load_settings
from .common import Commands, emit, read_recovery_key, say, stored


def add(commands: Commands, option: argparse.ArgumentParser) -> None:
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
        parents=[option],
    )


def run(args: argparse.Namespace) -> None:
    if args.keys_command == "generate":
        from ..data.secrets import cipher, encode_recovery

        emit(encode_recovery(cipher.new_key()))
        return
    from ..assembly import opened
    from ..domain.activity import HOST, system

    with opened(stored(load_settings(args.env_file), "keys")) as services:
        if args.keys_command == "init":
            recovery = services.vault.initialize()
            services.activity.record(system.KeysCreated(by=HOST))
            say(
                "Keys created. The recovery key below is shown this once. Keep it "
                "apart from any backup: without it, a backup cannot be restored "
                "on another machine."
            )
            emit(recovery)
        else:
            services.vault.import_master_key(read_recovery_key())
            services.activity.record(system.MasterKeyStored(by=HOST))
            say("Master key stored.")
