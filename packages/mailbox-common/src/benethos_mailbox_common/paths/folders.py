"""Where a program of Mailbox finds its settings file and its data: a file
named on purpose, and the folders of the operating system for this user
(CONCEPT 7.4), and the order in which a program looks for them. Each
program names its own file, variable and folders, and decides how a
relative path in its settings counts.

platformdirs comes with the extra ``paths``. Without it this module
cannot be imported, and says which extra is missing."""

from __future__ import annotations

import os
from dataclasses import dataclass
from pathlib import Path
from typing import Literal

try:
    import platformdirs
except ModuleNotFoundError as missing:
    raise ModuleNotFoundError(
        "benethos_mailbox_common.paths needs the extra paths: "
        "pip install 'benethos-mailbox-common[paths]'",
        name=missing.name,
    ) from missing


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


Origin = Literal["named", "working directory", "system"]


@dataclass(frozen=True, slots=True)
class Folders:
    """Where a command reads its settings and keeps its data. ``env_file``
    is read when it exists."""

    origin: Origin
    config: Path
    env_file: Path
    data: Path


def program_folders(
    app: str, env_file: Path | None, variable: str, local: Path, data: Path
) -> Folders:
    """The folders that apply to ``app``, first found first: the settings
    file named on purpose, ``env_file`` or the one ``variable`` names, with
    ``data`` beside it, the repository's layout in the working directory
    where it has the folder of ``local`` or ``data``, else those of the
    operating system."""
    named = named_file(env_file, variable)
    if named is not None:
        named = named.resolve()
        return Folders("named", named.parent, named, named.parent / data)
    if local.parent.is_dir() or data.is_dir():
        return Folders("working directory", local.parent, local, data)
    found = system_folders(app)
    return Folders("system", found.config, found.config / ".env", found.data)
