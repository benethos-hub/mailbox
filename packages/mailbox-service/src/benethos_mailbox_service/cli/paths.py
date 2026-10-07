"""``paths``: where this command's settings and data are."""

from __future__ import annotations

import argparse

from ..config import KEY_FILE_NAME, folders, load_settings
from .common import Commands

_ORIGINS = {
    "named": "the file named on purpose",
    "working directory": "the repository's folders in the working directory",
    "system": "the folders of the operating system",
}


def add(commands: Commands, option: argparse.ArgumentParser) -> None:
    commands.add_parser(
        "paths",
        help="name the settings file, the data folder and where the master key is",
        parents=[option],
    )


def run(args: argparse.Namespace) -> None:
    """Paths only, never a value of the settings."""
    from ..data.secrets import EnvKeyProvider, KeyringKeyProvider

    where = folders(args.env_file)
    settings = load_settings(args.env_file)
    found = where.env_file.is_file()
    if settings.key_provider == "keyring":
        key = KeyringKeyProvider().describe()
    elif settings.key_provider == "env":
        key = EnvKeyProvider(None).describe()
    elif settings.key_file is not None:
        key = f"the key file {settings.key_file.resolve()}"
    else:
        suggested = (where.config / KEY_FILE_NAME).resolve()
        key = f"a file, not set yet. Suggested: {suggested}"
    print(f"From:          {_ORIGINS[where.origin]}")
    print(
        f"Settings file: {where.env_file.resolve()}"
        + ("" if found else " (not there, the defaults apply)")
    )
    print(f"Data folder:   {settings.data_dir.resolve()}")
    print(f"Database:      {settings.database_path}")
    print(f"Master key:    {key}")
