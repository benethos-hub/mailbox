"""Where a program of Mailbox finds its settings file and its data: a file
named on purpose, and the folders of the operating system for this user
(CONCEPT 7.4). Each program decides the order and what its working
directory adds."""

from __future__ import annotations

import os
from dataclasses import dataclass
from pathlib import Path

import platformdirs


def named_file(env_file: Path | None, variable: str) -> Path | None:
    """A settings file named on purpose: ``env_file``, else the one the
    environment variable ``variable`` names. None without either."""
    if env_file is not None:
        return env_file
    named = os.environ.get(variable)
    return Path(named) if named else None


@dataclass(frozen=True, slots=True)
class SystemFolders:
    """The folders of the operating system for one program and this user."""

    # Settings and key files.
    config: Path
    # The database and what else the program keeps.
    data: Path


def system_folders(app: str) -> SystemFolders:
    """The config and the data folder of the operating system for ``app``
    and this user, never in a roaming profile on Windows. Where the system
    has one folder for both, as Windows and macOS do, each gets its own
    below it, so a copy of the data never carries a key file with it."""
    config = Path(platformdirs.user_config_dir(app, appauthor=False, roaming=False))
    data = Path(platformdirs.user_data_dir(app, appauthor=False, roaming=False))
    if config == data:
        return SystemFolders(config=config / "config", data=data / "data")
    return SystemFolders(config=config, data=data)
