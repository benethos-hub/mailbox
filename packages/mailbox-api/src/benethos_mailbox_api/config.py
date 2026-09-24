"""Settings, resolved from the environment and an optional ``.env`` file."""

from __future__ import annotations

from pydantic import Field, SecretStr
from pydantic_settings import BaseSettings, SettingsConfigDict


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
    # Bearer token every API request must carry. Unset means the API refuses
    # every request rather than serving without authentication. Read from
    # MAILBOX_API_KEY, not the prefixed MAILBOX_API_API_KEY.
    api_key: SecretStr | None = Field(default=None, validation_alias="MAILBOX_API_KEY")
    log_level: str = "INFO"
