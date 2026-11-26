"""``storage move --to postgres|sqlite``: the records moved between the
file of SQLite and the schema on the database server, both as the
settings name them, whatever ``MAILBOX_SERVICE_STORAGE`` says. With
``--check`` only held to their columns."""

from __future__ import annotations

import argparse
from pathlib import Path

from ..config import load_settings
from .common import Commands, UsageError, say


def add(commands: Commands, option: argparse.ArgumentParser) -> None:
    storage = commands.add_parser(
        "storage",
        help="the database of the service: move it between SQLite and "
        "PostgreSQL. Stop the service first.",
        parents=[option],
    )
    actions = storage.add_subparsers(dest="action", required=True)
    move = actions.add_parser(
        "move",
        help="copy every record into a new, empty database and compare it. "
        "The source stays as it is.",
        parents=[option],
    )
    move.add_argument(
        "--to",
        choices=["postgres", "sqlite"],
        required=True,
        help="postgres: from the file mailbox.db in the data folder to the "
        "schema of MAILBOX_SERVICE_DATABASE_URL. sqlite: back.",
    )
    move.add_argument(
        "--check",
        action="store_true",
        help="hold every value of the source to its column, write nothing",
    )


def run(args: argparse.Namespace) -> None:
    from ..assembly import database_server
    from ..data.move import check_move, move_records
    from ..data.storage import Server

    settings = load_settings(args.env_file)
    try:
        server = database_server(settings)
    except ValueError as exc:
        raise UsageError(f"storage move: {exc}") from None
    file = settings.database_path
    url = settings.database_url
    source: Path | Server
    target: Path | Server
    if args.to == "postgres":
        source, target = file, server
        source_name, target_name = str(file), f"the schema on {url}"
    else:
        source, target = server, file
        source_name, target_name = f"the schema on {url}", str(file)
    if args.check:
        found = check_move(source)
        say(
            f"Every value of {source_name} fits its column: {found.rows} rows"
            f" in {found.tables} tables. Nothing was written."
        )
        return
    moved = move_records(source, target)
    say(
        f"Moved {moved.rows} rows in {moved.tables} tables from {source_name}"
        f" to {target_name}, compared table by table. The source is as it"
        f" was. Set MAILBOX_SERVICE_STORAGE={args.to} to start the service on"
        " the new database."
    )
