"""Where the live setup of the agents is, and the settings of a check:
from their file alone, and only for the mailbox service of
containers/live on this machine."""

from __future__ import annotations

import argparse
import os
import sys
from pathlib import Path
from urllib.parse import urlsplit

from benethos_mailbox_agents.settings import PREFIX, Settings, load_settings

ROOT = Path(__file__).resolve().parents[3]


LIVE = ROOT / "containers" / "live" / "mailbox-agents"


ENV = LIVE / "secrets" / "agent.env"


LIST = LIVE / "categorization.json"


# The hosts of a mailbox service on this machine, as containers/live has it.
LOOPBACK = frozenset({"127.0.0.1", "localhost", "::1"})


# The port containers/live/mailbox-agents/compose.yaml publishes its mailbox service on.
# A service on this machine at another port, such as the default 8080, may be
# a real one: the check refuses it.
LIVE_PORT = 38081


# The days of mail a check reads, as the invented mail of mail.py spans.
DAYS = 30


def live_settings(path: Path, script: str) -> Settings:
    """The settings in the file at ``path``, every ``MAILBOX_AGENTS_``
    variable of the environment aside. Exits when the file is missing or
    names no account, and with code 2 when the mailbox service is not the
    one of containers/live, on this machine at :data:`LIVE_PORT`.
    ``script`` names the check in what it says."""
    if not path.is_file():
        sys.exit(
            f"{script}: no settings at {path},"
            " run containers/live/mailbox-agents/setup.sh"
        )
    aside = {
        name: os.environ.pop(name)
        for name in list(os.environ)
        if name.upper().startswith(PREFIX)  # read without regard to case
    }
    try:
        found = load_settings(path)
    finally:
        os.environ.update(aside)
    url = urlsplit(found.service_url or "")
    try:
        port = url.port
    except ValueError:
        port = None
    if url.hostname not in LOOPBACK or port != LIVE_PORT:
        print(
            f"{script}: the mailbox service is not the one of containers/live, "
            f"on this machine at port {LIVE_PORT}: a live check runs against "
            "the test account of containers/live only",
            file=sys.stderr,
        )
        raise SystemExit(2)
    if not found.accounts:
        sys.exit(
            f"{script}: the settings name no account, the check needs the test one"
        )
    for account in found.accounts:
        print(f"live: account {account} at {found.service_url}")
    return found


def parse_settings(script: str, description: str) -> Settings:
    """The settings of the file the command line names with ``--env-file``,
    containers/live/mailbox-agents/secrets/agent.env when it names none."""
    parser = argparse.ArgumentParser(description=description)
    parser.add_argument("--env-file", type=Path, default=ENV)
    args = parser.parse_args()
    return live_settings(args.env_file, script)
