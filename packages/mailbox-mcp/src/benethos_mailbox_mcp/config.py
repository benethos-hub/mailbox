"""The optional settings file of the MCP server: where it is, and its
values put into the environment, which wins over them (CONCEPT 7.4)."""

from __future__ import annotations

import os
from pathlib import Path

from dotenv import dotenv_values

from benethos_mailbox_common.paths import folders

APP = "benethos-mailbox-mcp"
# The layout of the repository, relative to the working directory.
ENV_FILE = f"config/{APP}/.env"
# Names another settings file, as --env-file does on the command line.
ENV_FILE_VARIABLE = "MAILBOX_MCP_ENV_FILE"
# What the file may set: the MCP server's settings and the service's
# address and token, nothing else of the process.
PREFIXES = ("MAILBOX_MCP_", "MAILBOX_SERVICE_")


def config_folder() -> Path:
    """The config folder of the operating system for this user."""
    return folders.system_folders(APP)[0]


def settings_file(env_file: Path | None = None) -> Path | None:
    """The file to read, first found first: ``env_file``, else the one
    ``MAILBOX_MCP_ENV_FILE`` names, which must exist. Else ``ENV_FILE`` in
    the working directory, else ``.env`` in the config folder of the
    operating system, when they exist."""
    env_file = folders.named_file(env_file, ENV_FILE_VARIABLE)
    if env_file is not None:
        if not env_file.is_file():
            raise FileNotFoundError(f"settings file {env_file} not found")
        return env_file.resolve()
    for candidate in (Path(ENV_FILE), config_folder() / ".env"):
        if candidate.is_file():
            return candidate.resolve()
    return None


def load(env_file: Path | None = None) -> Path | None:
    """Put the settings of the file into the environment where it has none
    of its own, and name the file. None when there is no file."""
    found = settings_file(env_file)
    if found is None:
        return None
    for name, value in dotenv_values(found).items():
        if value is not None and name.startswith(PREFIXES):
            os.environ.setdefault(name, value)
    return found
