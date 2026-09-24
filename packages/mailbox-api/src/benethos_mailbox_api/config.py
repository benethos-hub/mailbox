"""Settings, resolved from the environment and an optional ``.env`` file."""

from __future__ import annotations

from pathlib import Path
from typing import Literal

from pydantic import Field, SecretStr
from pydantic_settings import BaseSettings, SettingsConfigDict

# Relative to the working directory. Template: .env.example beside it.
ENV_FILE = "config/benethos-mailbox-api/.env"


class Settings(BaseSettings):
    """Every setting of the REST service. Prefix ``MAILBOX_API_``."""

    model_config = SettingsConfigDict(
        env_prefix="MAILBOX_API_",
        env_file=ENV_FILE,
        extra="ignore",
        populate_by_name=True,
    )

    host: str = "127.0.0.1"
    port: int = 8080
    # The built-in admin key. Read from MAILBOX_API_KEY, not the prefixed
    # MAILBOX_API_API_KEY.
    api_key: SecretStr | None = Field(default=None, validation_alias="MAILBOX_API_KEY")
    log_level: str = "INFO"
    # Where the database lives. A relative path counts from the working
    # directory.
    data_dir: Path = Path("data/benethos-mailbox-api")
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
    # Sync worker: seconds between two polls of every folder. 0 switches the
    # worker off.
    sync_interval: int = Field(default=300, ge=0)
    # Sync worker: watch the inbox over IMAP IDLE, which needs a second
    # connection per account.
    sync_idle: bool = True

    @property
    def database_path(self) -> Path:
        return (self.data_dir / "mailbox.db").resolve()
