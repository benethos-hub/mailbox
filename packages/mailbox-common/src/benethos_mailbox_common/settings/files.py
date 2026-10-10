"""The settings of a program of Mailbox: what the command line gives,
else the environment, else a settings file, else the default (CONCEPT
7.4). A program describes them as a class of ``FileSettings``, with the
fields of pydantic and its prefix in ``model_config``, and loads them
with ``load``. Where the file is, the program decides.

The one module that imports pydantic-settings. It comes with the extra
``settings``. Without it this module cannot be imported, and says which
extra is missing."""

from __future__ import annotations

from pathlib import Path
from typing import Any, TypeVar

try:
    from pydantic_settings import BaseSettings, SettingsConfigDict
except ModuleNotFoundError as missing:
    raise ModuleNotFoundError(
        "benethos_mailbox_common.settings needs the extra settings: "
        "pip install 'benethos-mailbox-common[settings]'",
        name=missing.name,
    ) from missing


class FileSettings(BaseSettings):
    """The base of a program's settings. A name the program does not know
    is left alone, so a file may hold the settings of several programs."""

    model_config = SettingsConfigDict(extra="ignore")


S = TypeVar("S", bound=FileSettings)


def load(settings: type[S], env_file: Path | None, **given: Any) -> S:
    """``settings`` as ``given`` names them, else the environment, else
    ``env_file``, else their defaults. Without a file, or one that does
    not exist, only the environment is read."""
    found = env_file if env_file is not None and env_file.is_file() else None
    return settings(_env_file=found, **given)
