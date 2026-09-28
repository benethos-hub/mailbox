"""Settings, resolved from the environment and an optional ``.env`` file."""

from __future__ import annotations

import os
from pathlib import Path
from typing import Literal, Self

from pydantic import Field, SecretStr, field_validator, model_validator
from pydantic_settings import BaseSettings, SettingsConfigDict

# Relative to the working directory, read when it exists. Template:
# .env.example beside it.
ENV_FILE = "config/benethos-mailbox-service/.env"
# Names another settings file, as --env-file does on the command line.
ENV_FILE_VARIABLE = "MAILBOX_SERVICE_ENV_FILE"


class Settings(BaseSettings):
    """Every setting of the REST service. Prefix ``MAILBOX_SERVICE_``."""

    model_config = SettingsConfigDict(
        env_prefix="MAILBOX_SERVICE_",
        env_file=ENV_FILE,
        extra="ignore",
        populate_by_name=True,
    )

    host: str = "127.0.0.1"
    port: int = Field(default=8080, ge=1, le=65535)
    # The address people reach the service at, e.g. https://mail.example.org
    # behind a proxy. Builds the OAuth redirect address, which the provider
    # must know. Empty: taken from each request.
    public_url: str | None = None
    # Behind a reverse proxy: the proxy's address (or several, separated by
    # commas, or "*"), whose X-Forwarded-For, -Proto and -Host headers are
    # believed. They give the client address that the sign-in throttle
    # counts, the scheme the session cookie's Secure flag follows and the
    # host the OAuth redirect is built from without a public URL. Empty:
    # only a proxy on 127.0.0.1 is believed.
    forwarded_allow_ips: str | None = None
    # As uvicorn names them, in any case.
    log_level: Literal["critical", "error", "warning", "info", "debug", "trace"] = (
        "info"
    )
    # Where the database lives. A relative path counts from the working
    # directory.
    data_dir: Path = Path("data/benethos-mailbox-service")
    # "memory" keeps nothing across restarts. For tests and trying things out.
    storage: Literal["sqlite", "memory"] = "sqlite"
    # Where the master key comes from.
    key_provider: Literal["keyring", "file", "env"] = "keyring"
    key_file: Path | None = None
    master_key: SecretStr | None = Field(
        default=None, validation_alias="MAILBOX_SERVICE_MASTER_KEY"
    )
    # Autodiscovery: whether to ask Thunderbird's ISPDB, which tells Mozilla
    # the domain being set up.
    discovery_ispdb: bool = True
    # Host names that may resolve to private addresses, e.g. an internal
    # mail server: autodiscovery may look them up and accounts may use them
    # (CONCEPT 5.8, rule 6). A JSON list.
    discovery_internal_hosts: list[str] = Field(default_factory=list)
    # Sync worker: seconds between two polls of every folder. 0 switches the
    # worker off.
    sync_interval: int = Field(default=300, ge=0)
    # Sync worker: watch the inbox over IMAP IDLE, which needs a second
    # connection per account.
    sync_idle: bool = True
    # Webhooks: how many times a post is tried before its events are
    # dropped, the pause after the first failure in seconds, doubled after
    # each further one up to the longest, and how long a receiver may take.
    webhook_attempts: int = Field(default=8, ge=1)
    webhook_first_retry: float = Field(default=30.0, gt=0)
    webhook_longest_retry: float = Field(default=3600.0, gt=0)
    webhook_timeout: float = Field(default=10.0, gt=0)
    # Change feed: days a change is kept. A client that asks from an older
    # point starts again from the current state.
    changes_days: int = Field(default=7, ge=1)
    # OAuth for Microsoft accounts: the app the operator registered in
    # Microsoft Entra ID. Without a client id, Microsoft accounts cannot be
    # connected. The secret from a file (a container secret) or from the
    # environment.
    oauth_microsoft_client_id: str | None = None
    oauth_microsoft_client_secret: SecretStr | None = None
    oauth_microsoft_client_secret_file: Path | None = None
    # Who may sign in: common (personal and work or school accounts),
    # consumers, organizations, or one tenant's id or domain.
    oauth_microsoft_tenant: str = "common"

    @field_validator("log_level", mode="before")
    @classmethod
    def _lower(cls, value: object) -> object:
        return value.lower() if isinstance(value, str) else value

    @model_validator(mode="after")
    def _retries(self) -> Self:
        if self.webhook_longest_retry < self.webhook_first_retry:
            raise ValueError(
                "webhook_longest_retry must not be shorter than webhook_first_retry"
            )
        return self

    def oauth_microsoft_secret(self) -> SecretStr | None:
        """The client secret, from its file if one is named."""
        if self.oauth_microsoft_client_secret_file is not None:
            text = self.oauth_microsoft_client_secret_file.read_text(encoding="utf-8")
            return SecretStr(text.strip())
        return self.oauth_microsoft_client_secret

    @property
    def database_path(self) -> Path:
        return (self.data_dir / "mailbox.db").resolve()


def named_settings_file(env_file: Path | None = None) -> Path | None:
    """A settings file named on purpose: ``env_file``, else the one
    ``MAILBOX_SERVICE_ENV_FILE`` names. None without either."""
    if env_file is not None:
        return env_file
    named = os.environ.get(ENV_FILE_VARIABLE)
    return Path(named) if named else None


def settings_file(env_file: Path | None = None) -> Path | None:
    """The file the settings are read from, None when there is none."""
    named = named_settings_file(env_file)
    if named is not None:
        return named.resolve()
    default = Settings.model_config.get("env_file")
    if isinstance(default, str | Path) and Path(default).is_file():
        return Path(default).resolve()
    return None


def load_settings(env_file: Path | None = None) -> Settings:
    """The settings of a command. A file named on purpose must exist, and
    a relative path in the settings then counts from its folder, so the
    service finds its data wherever it is started. Without one it reads
    ``ENV_FILE`` if it exists, and relative paths count from the working
    directory."""
    named = named_settings_file(env_file)
    if named is None:
        return Settings()
    if not named.is_file():
        raise FileNotFoundError(f"settings file {named} not found")
    settings = Settings(_env_file=named)
    base = named.resolve().parent
    return settings.model_copy(
        update={
            key: base / value
            for key in ("data_dir", "key_file", "oauth_microsoft_client_secret_file")
            if isinstance(value := getattr(settings, key), Path)
            and not value.is_absolute()
        }
    )
