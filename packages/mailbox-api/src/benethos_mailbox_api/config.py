"""Settings, resolved from the environment and an optional ``.env`` file."""

from __future__ import annotations

from pathlib import Path
from typing import Literal

from platformdirs import user_data_dir
from pydantic import Field, SecretStr
from pydantic_settings import BaseSettings, SettingsConfigDict

APP_NAME = "benethos-mailbox-api"


class Settings(BaseSettings):
    """Every setting of the REST service. Prefix ``MAILBOX_API_``."""

    model_config = SettingsConfigDict(
        env_prefix="MAILBOX_API_",
        env_file=".env",
        extra="ignore",
        populate_by_name=True,
    )

    host: str = "127.0.0.1"
    port: int = 8080
    # The built-in admin key. Read from MAILBOX_API_KEY, not the prefixed
    # MAILBOX_API_API_KEY.
    api_key: SecretStr | None = Field(default=None, validation_alias="MAILBOX_API_KEY")
    log_level: str = "INFO"
    # Where the database lives. Defaults to the per-user data directory.
    data_dir: Path | None = None
    # "memory" keeps nothing across restarts. For tests and trying things out.
    storage: Literal["sqlite", "memory"] = "sqlite"
    # Where the master key comes from.
    key_provider: Literal["keyring", "file", "env"] = "keyring"
    key_file: Path | None = None
    master_key: SecretStr | None = Field(
        default=None, validation_alias="MAILBOX_API_MASTER_KEY"
    )
    # Autodiscovery: whether to ask Thunderbird's ISPDB, which tells Mozilla
    # the domain being set up.
    discovery_ispdb: bool = True
    # Autodiscovery: host names that may resolve to private addresses, e.g.
    # an internal mail server. A JSON list.
    discovery_internal_hosts: list[str] = Field(default_factory=list)

    @property
    def database_path(self) -> Path:
        base = self.data_dir or Path(user_data_dir(APP_NAME, appauthor=False))
        return base / "mailbox.db"
