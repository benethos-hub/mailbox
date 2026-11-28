"""A command of the agents as a process of a live check: its environment
without a setting of the shell, and the command line that starts it on
the settings file of the check."""

from __future__ import annotations

import os
import sys
from pathlib import Path

from benethos_mailbox_agents.settings import PREFIX


def clean_environment(**values: str) -> dict[str, str]:
    """The environment of this process without a setting of the agents,
    and ``values`` as the settings they name, ``data_dir`` as
    ``MAILBOX_AGENTS_DATA_DIR``."""
    found = {k: v for k, v in os.environ.items() if not k.upper().startswith(PREFIX)}
    found.update({f"{PREFIX}{name.upper()}": value for name, value in values.items()})
    return found


def agents_command(env_file: Path, *args: str) -> list[str]:
    """The command line of the agents with ``args``, on ``env_file``."""
    return [sys.executable, "-m", "benethos_mailbox_agents", "--env-file"] + [
        str(env_file),
        *args,
    ]
