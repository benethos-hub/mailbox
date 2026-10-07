"""The command line: ``benethos-mailbox-service serve`` and the host
tools. One module per command, each with ``add``, which puts it on the
parser, and ``run``. ``common`` holds what they share."""

from __future__ import annotations

import argparse
from pathlib import Path
from types import ModuleType

from .. import __version__
from . import backup, keys, openapi, paths, restore, serve, users
from .common import ENV_FILE_HELP, expected, message, say

# In the order the help names them.
COMMANDS: dict[str, ModuleType] = {
    "serve": serve,
    "openapi": openapi,
    "paths": paths,
    "users": users,
    "keys": keys,
    "backup": backup,
    "restore": restore,
}


def main(argv: list[str] | None = None) -> int:
    args = parser().parse_args(argv)
    try:
        COMMANDS[args.command].run(args)
    except expected() as exc:
        say(f"error: {message(exc)}")
        return 1
    return 0


def parser() -> argparse.ArgumentParser:
    found = argparse.ArgumentParser(prog="benethos-mailbox-service")
    found.add_argument("--version", action="version", version=__version__)
    found.add_argument(
        "--env-file", type=Path, default=None, metavar="PATH", help=ENV_FILE_HELP
    )
    # The same option after a command. Given there, it wins.
    option = argparse.ArgumentParser(add_help=False)
    option.add_argument(
        "--env-file",
        type=Path,
        default=argparse.SUPPRESS,
        metavar="PATH",
        help=ENV_FILE_HELP,
    )
    commands = found.add_subparsers(dest="command", required=True)
    for command in COMMANDS.values():
        command.add(commands, option)
    return found


__all__ = ["main", "parser"]
