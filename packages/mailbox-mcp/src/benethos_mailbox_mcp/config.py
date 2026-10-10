"""The settings of the MCP server: the command line, else the environment,
else the optional settings file, else the defaults (CONCEPT 7.4). Where
the file is, and the settings read with it."""

from __future__ import annotations

from pathlib import Path
from typing import Literal

from pydantic import Field, SecretStr, field_validator

from benethos_mailbox_common.paths import folders
from benethos_mailbox_common.settings import files

APP = "benethos-mailbox-mcp"
# The layout of the repository, relative to the working directory.
ENV_FILE = f"config/{APP}/.env"
# Names another settings file, as --env-file does on the command line.
ENV_FILE_VARIABLE = "MAILBOX_MCP_ENV_FILE"
PREFIX = "MAILBOX_MCP_"

Transport = Literal["stdio", "streamable-http"]
LogLevel = Literal["DEBUG", "INFO", "WARNING", "ERROR"]


class Settings(files.FileSettings):
    """Every setting of the MCP server, prefix ``MAILBOX_MCP_``, and the
    service's address and token by the names the client reads. An empty
    value counts as not set."""

    model_config = {
        "env_prefix": PREFIX,
        "env_ignore_empty": True,
        "populate_by_name": True,
    }

    transport: Transport = "stdio"
    host: str = "127.0.0.1"
    port: int = Field(default=8000, ge=1, le=65535)
    path: str = "/mcp"
    # Comma-separated Host and Origin values, e.g. mcp.example.org:443.
    allowed_hosts: str = ""
    allowed_origins: str = ""
    log_level: LogLevel = "INFO"
    # The one token callers over HTTP bring. None: no guard.
    bearer_token: SecretStr | None = None
    # None: the client's default address.
    service_url: str | None = Field(default=None, alias="MAILBOX_SERVICE_URL")
    service_token: SecretStr | None = Field(default=None, alias="MAILBOX_SERVICE_TOKEN")
    service_allow_http: bool = Field(default=False, alias="MAILBOX_SERVICE_ALLOW_HTTP")

    @field_validator("log_level", mode="before")
    @classmethod
    def _upper(cls, value: object) -> object:
        return value.upper() if isinstance(value, str) else value

    @field_validator("bearer_token", mode="before")
    @classmethod
    def _blank_is_none(cls, value: object) -> object:
        """A token of blanks guards nothing: it counts as none."""
        if isinstance(value, str):
            return value.strip() or None
        return value


def config_folder() -> Path:
    """The config folder of the operating system for this user."""
    return folders.system_folders(APP).config


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


def load_settings(env_file: Path | None, **given: object) -> Settings:
    """The settings, ``given`` on the command line first. A value of None
    in ``given`` was not given."""
    named = {name: value for name, value in given.items() if value is not None}
    return files.load(Settings, env_file, **named)


def variable(name: str) -> str:
    """The name in the environment and the file of a setting, by its
    field or the name it is read by."""
    field = Settings.model_fields.get(name)
    if field is None:
        return name
    return field.alias or PREFIX + name.upper()
