"""The settings of the MCP server: the command line, else the environment,
else the optional settings file, else the defaults (CONCEPT 7.4). Where
the file is, and the settings read with it."""

from __future__ import annotations

from pathlib import Path
from typing import Literal, Self

from pydantic import (
    Field,
    SecretStr,
    ValidationInfo,
    field_validator,
    model_validator,
)

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
    allowed_hosts: files.Names = Field(default_factory=list)
    allowed_origins: files.Names = Field(default_factory=list)
    log_level: LogLevel = "INFO"
    # How often the server asks what its token may do. 0: only at start.
    rights_seconds: int = Field(default=60, ge=0)
    # Lists every tool and runs none, without a service or a token: for a
    # directory that reads the tool list in a sandbox. Never with a token.
    catalogue: bool = False
    # The one token callers over HTTP bring. None: no guard. Or from a
    # file, a container secret, never both.
    bearer_token: SecretStr | None = None
    bearer_token_file: Path | None = None
    # None: the client's default address.
    service_url: str | None = Field(default=None, alias="MAILBOX_SERVICE_URL")
    service_token: SecretStr | None = Field(default=None, alias="MAILBOX_SERVICE_TOKEN")
    service_token_file: Path | None = Field(
        default=None, alias="MAILBOX_SERVICE_TOKEN_FILE"
    )
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

    @field_validator("bearer_token_file", "service_token_file")
    @classmethod
    def _one_way(cls, value: Path | None, info: ValidationInfo) -> Path | None:
        """A token from a file that can be read and holds one, and not
        beside the token itself. The error names the setting, never what
        the file holds."""
        token = (info.field_name or "").removesuffix("_file")
        if value is not None:
            if info.data.get(token) is not None:
                raise ValueError(f"set {variable(token)} or this, not both")
            _read(value)
        return value

    @model_validator(mode="after")
    def _from_files(self) -> Self:
        if self.bearer_token_file is not None:
            self.bearer_token = SecretStr(_read(self.bearer_token_file))
        if self.service_token_file is not None:
            self.service_token = SecretStr(_read(self.service_token_file))
        return self


def _read(path: Path) -> str:
    """The token in the file at ``path``, without the blanks around it."""
    try:
        found = files.secret_file(path)
    except (OSError, UnicodeDecodeError):
        raise ValueError("the file cannot be read") from None
    if not found:
        raise ValueError("the file holds no token")
    return found


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
    return files.load(Settings, env_file, **_rebased(env_file, named))


class _Paths(files.FileSettings):
    """The settings that hold a path, read as they are written, so a
    relative one can count from the settings file before the settings are
    checked: a token's file is read while they are."""

    model_config = {
        "env_prefix": PREFIX,
        "env_ignore_empty": True,
        "populate_by_name": True,
    }

    bearer_token_file: str | None = None
    service_token_file: str | None = Field(
        default=None, alias="MAILBOX_SERVICE_TOKEN_FILE"
    )


def _rebased(env_file: Path | None, given: dict[str, object]) -> dict[str, object]:
    """``given`` with each relative token file it does not name counted
    from the folder of ``env_file``. Without a file, and in the layout of
    the repository, paths count from the working directory and ``given``
    stays as it is."""
    if env_file is None or env_file.resolve() == Path(ENV_FILE).resolve():
        return given
    found = files.load(_Paths, env_file)
    moved = dict(given)
    for key in ("bearer_token_file", "service_token_file"):
        value = getattr(found, key)
        if key in given or not value or Path(value).is_absolute():
            continue
        # By the alias where there is one: given by the field's name, an
        # older pydantic-settings lets the file's value under the alias win.
        moved[Settings.model_fields[key].alias or key] = env_file.parent / value
    return moved


def variable(name: str) -> str:
    """The name in the environment and the file of a setting, by its
    field or the name it is read by."""
    return files.env_name(Settings, name)
