"""The console script ``benethos-mailbox-agents``.

Each command is a function in :mod:`.commands`. The command line reads the
settings once, sets up the log and turns an error of this package into a
sentence on stderr and an exit code: 2 for a configuration to correct, a
contract or a mailbox service of another version, 1 for any other,
such as an upstream that is away or a state file that cannot be read.
See docs/mailbox-agents/ARCHITECTURE.md.
"""

from __future__ import annotations

import argparse
import os
import sys
from collections.abc import Sequence
from pathlib import Path

from benethos_mailbox_common.values import text as text_values

from .. import __version__, logbook
from ..errors import (
    ConfigError,
    ContractError,
    MailboxAgentError,
    ServiceVersionError,
)
from ..settings import DEFAULT_ENV_FILE, PREFIX, load_settings
from . import commands, status, storage

__all__ = ["PROG", "build_parser", "main"]

PROG = "benethos-mailbox-agents"


def _agent(parser: argparse.ArgumentParser) -> None:
    parser.add_argument("--agent", required=True, help="the agent, such as counting")


def build_parser() -> argparse.ArgumentParser:
    """The argument parser, apart from ``main`` so a test can read it."""
    parser = argparse.ArgumentParser(
        prog=PROG,
        description="Agents that read and sort a mailbox.",
    )
    parser.add_argument("--version", action="version", version=f"{PROG} {__version__}")
    parser.add_argument(
        "--env-file",
        type=Path,
        default=None,
        help=f"the settings file, {DEFAULT_ENV_FILE.as_posix()} when it exists",
    )
    sub = parser.add_subparsers(dest="command", metavar="command")

    found = sub.add_parser("worker", help="run one agent until stopped")
    _agent(found)
    found.set_defaults(handler=commands.worker)

    found = sub.add_parser("run", help="one pass of one agent, then stop")
    _agent(found)
    found.set_defaults(handler=commands.run)

    found = sub.add_parser(
        "backfill", help="take the messages of recent days up anew, then run them"
    )
    _agent(found)
    found.add_argument(
        "--days", type=int, default=None, help=f"{PREFIX}BACKFILL_DAYS if unset"
    )
    found.set_defaults(handler=commands.backfill)

    found = sub.add_parser(
        "report", help="what an agent decided and did, with subject and sender"
    )
    _agent(found)
    found.add_argument("--limit", type=int, default=50, help="the newest messages")
    found.add_argument("--state", default=None, help="only messages in this state")
    found.add_argument(
        "--offline",
        action="store_true",
        help="from the state file alone, without subject and sender",
    )
    found.set_defaults(handler=commands.report)

    found = sub.add_parser(
        "status",
        help="whether each agent is ready, the folders that matter to it, "
        "and its counts",
    )
    found.set_defaults(handler=status.status)

    found = sub.add_parser(
        "eval", help="run an agent over a gold set, beside its rules, and report"
    )
    _agent(found)
    found.add_argument("--gold", type=Path, required=True, help="the gold file")
    found.add_argument(
        "--recognizer",
        default=None,
        help="one recognizer of the agent alone, in its own space, such as "
        "invoice of categorization",
    )
    found.add_argument(
        "--reports",
        type=Path,
        default=None,
        help="where the report goes: reports/mailbox-agents in the layout "
        "of the repository, else reports/ in the data folder",
    )
    found.set_defaults(handler=commands.evaluate)

    found = sub.add_parser(
        "health", help="exit 0 while the agent's loop makes progress, else 1"
    )
    _agent(found)
    found.set_defaults(handler=commands.health)

    found = sub.add_parser(
        "check",
        help="whether the lists of several instances of an agent fit together",
    )
    _agent(found)
    found.add_argument(
        "instances",
        nargs="+",
        metavar="INSTANCE=FILE",
        help="the list of each instance, such as partner=partner.json",
    )
    found.set_defaults(handler=commands.check_lists)

    found = sub.add_parser(
        "cockpit",
        help="serve the read-only pages of what every agent did, until stopped",
    )
    found.set_defaults(handler=commands.cockpit)

    found = sub.add_parser("paths", help="where the settings and the state files are")
    found.set_defaults(handler=status.paths)

    storage.add(sub)
    return parser


def main(argv: Sequence[str] | None = None) -> int:
    """Run the command line and answer with the exit code."""
    # The state file holds what the agents decided about the mail: readable
    # by its owner only. Windows keeps its own rights and ignores this.
    os.umask(0o077)
    parser = build_parser()
    args = parser.parse_args(argv)
    if args.command is None:
        parser.print_help()
        return 0
    try:
        settings = load_settings(args.env_file)
        logbook.configure(settings.log_level)
        code: int = args.handler(args, settings)
    except (ConfigError, ContractError, ServiceVersionError) as exc:
        print(f"{PROG}: {text_values.escaped(exc.message)}", file=sys.stderr)
        return 2
    except MailboxAgentError as exc:
        print(f"{PROG}: {text_values.escaped(exc.message)}", file=sys.stderr)
        return 1
    return code
