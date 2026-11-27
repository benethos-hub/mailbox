"""Where the agents read their settings and keep their state files, as
the service finds its own (docs/mailbox-agents/concept/configuration.md):
the settings file named on purpose, the layout of the repository in the
working directory, else the folders of the operating system."""

from __future__ import annotations

from pathlib import Path
from typing import Any

from benethos_mailbox_common.paths import folders as system
from benethos_mailbox_common.settings import files

__all__ = [
    "APP",
    "DATA_DIR",
    "DEFAULT_ENV_FILE",
    "ENV_FILE_VARIABLE",
    "PATH_SETTINGS",
    "Folders",
    "Origin",
    "folders",
    "rebased",
]

APP = "benethos-mailbox-agents"
# The layout of the repository, relative to the working directory. The
# settings file is read when it exists. The example beside it lists every
# setting.
DEFAULT_ENV_FILE = Path("config") / APP / ".env"
DATA_DIR = Path("data") / APP
# Names another settings file, as --env-file does on the command line.
ENV_FILE_VARIABLE = "MAILBOX_AGENTS_ENV_FILE"
# The settings that hold a path. A relative one counts from the folder of
# the settings file, outside the layout of the repository.
PATH_SETTINGS = (
    "data_dir",
    "categorization_file",
    "filing_file",
    "inquiries_patterns_file",
    "ca_file",
    "service_token_file",
    "gateway_key_file",
    "otlp_headers_file",
    "a2a_token_file",
)


# Where a command reads its settings and keeps its state files.
Folders = system.Folders
Origin = system.Origin


def folders(env_file: Path | None = None) -> Folders:
    """The folders that apply, first found first: the settings file named
    on purpose, ``env_file`` or the one ``MAILBOX_AGENTS_ENV_FILE`` names,
    the repository's layout in the working directory where it has either
    folder, else those of the operating system. ``data`` holds the state
    files unless ``MAILBOX_AGENTS_DATA_DIR`` moves them."""
    return system.program_folders(
        APP, env_file, ENV_FILE_VARIABLE, DEFAULT_ENV_FILE, DATA_DIR
    )


class _Paths(files.FileSettings):
    """The settings that hold a path, read as they are written, so a
    relative one can count from the settings file before the settings are
    checked: a secret's file is read while they are."""

    model_config = {"env_prefix": "MAILBOX_AGENTS_", "env_file_encoding": "utf-8"}

    data_dir: str | None = None
    categorization_file: str | None = None
    filing_file: str | None = None
    inquiries_patterns_file: str | None = None
    ca_file: str | None = None
    service_token_file: str | None = None
    gateway_key_file: str | None = None
    otlp_headers_file: str | None = None
    a2a_token_file: str | None = None


def rebased(where: Folders, given: dict[str, Any]) -> dict[str, Any]:
    """``given`` with each path setting it does not name counted from the
    folder of the settings file, and the data folder of ``where`` when no
    setting names one. In the layout of the repository paths count from
    the working directory, as they did before, and ``given`` stays as it
    is."""
    if where.origin == "working directory":
        return given
    found = files.load(_Paths, where.env_file)
    moved = dict(given)
    for key in PATH_SETTINGS:
        value = getattr(found, key)
        if key in given or not value or Path(value).is_absolute():
            continue
        moved[key] = where.config / value
    if "data_dir" not in given and not found.data_dir:
        moved["data_dir"] = where.data
    return moved
