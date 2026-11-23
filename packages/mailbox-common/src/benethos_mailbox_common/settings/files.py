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
    from pydantic_settings import BaseSettings, NoDecode, SettingsConfigDict
except ModuleNotFoundError as missing:
    raise ModuleNotFoundError(
        "benethos_mailbox_common.settings needs the extra settings: "
        "pip install 'benethos-mailbox-common[settings]'",
        name=missing.name,
    ) from missing

# NoDecode marks a field whose value the program splits itself, such as a
# list given as names between commas, so the environment does not read it
# as JSON.
__all__ = ["FileSettings", "NoDecode", "S", "env_name", "load", "problems"]


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


def env_name(settings: type[FileSettings], field: str) -> str:
    """The name of a setting in the environment and the file: its alias,
    else the prefix of ``settings`` and the field in capitals. A name
    that is no field, such as an alias, comes back as it is."""
    found = settings.model_fields.get(field)
    if found is None:
        return field
    prefix = settings.model_config.get("env_prefix", "")
    return found.alias or f"{prefix}{field.upper()}"


def problems(settings: type[FileSettings], exc: Exception) -> list[str]:
    """Each problem of a validation error as ``NAME: rule``, never the
    input, which may be a secret. A problem of the settings as a whole
    carries the rule alone."""
    # pydantic's ValidationError, which this module does not import.
    errors = exc.errors(include_input=False, include_url=False)  # type: ignore[attr-defined]
    found: list[str] = []
    for error in errors:
        place = [str(part) for part in error["loc"]]
        if not place:
            found.append(error["msg"])
            continue
        name = ".".join([env_name(settings, place[0]), *place[1:]])
        found.append(f"{name}: {error['msg']}")
    return found
