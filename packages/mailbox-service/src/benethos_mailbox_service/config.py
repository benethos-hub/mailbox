"""Settings, resolved from the environment and an optional ``.env`` file,
and the folders a command reads them from and keeps its data in."""

from __future__ import annotations

from dataclasses import dataclass
from pathlib import Path
from typing import Literal, Self

from pydantic import Field, SecretStr, field_validator, model_validator
from pydantic_settings import BaseSettings, SettingsConfigDict

# Named apart from folders() below.
from benethos_mailbox_common.paths import folders as system

APP = "benethos-mailbox-service"
# The layout of the repository, relative to the working directory. The
# settings file is read when it exists. Template: .env.example beside it.
ENV_FILE = f"config/{APP}/.env"
DATA_DIR = Path("data") / APP
# Names another settings file, as --env-file does on the command line.
ENV_FILE_VARIABLE = "MAILBOX_SERVICE_ENV_FILE"
# The name `paths` suggests for a key file in the config folder.
KEY_FILE_NAME = "master.key"
# The settings that hold a path. A relative one counts from the folder
# of the settings file.
PATH_SETTINGS = (
    "data_dir",
    "key_file",
    "oauth_microsoft_client_secret_file",
    "oauth_google_client_secret_file",
)


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
    # believed. They give the client address that the sign-in throttle and
    # the request limit count, the scheme the session cookie's Secure flag
    # follows and the host the OAuth redirect is built from without a
    # public URL. Empty: only a proxy on 127.0.0.1 is believed.
    forwarded_allow_ips: str | None = None
    # As uvicorn names them, in any case.
    log_level: Literal["critical", "error", "warning", "info", "debug", "trace"] = (
        "info"
    )
    # Where the database lives. Without it the data folder that `paths`
    # names. A relative path counts from the folder of the settings file.
    data_dir: Path = DATA_DIR
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
    # Sync worker: wait for the server to report a change, over IMAP IDLE,
    # which needs a second connection per account, or a JMAP server's
    # event source.
    sync_idle: bool = True
    # Sync worker: accounts watched over IDLE at once. Each watcher holds a
    # thread of its own, outside the pool that answers requests. Further
    # accounts are polled only.
    sync_watchers: int = Field(default=50, ge=1)
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
    # The audits of sends and of administration: days a record is kept.
    # 0 keeps every record.
    audit_days: int = Field(default=90, ge=0)
    # Requests a minute per API token or UI session, and per client address
    # for requests without a credential. A burst of half as many passes at
    # once. 0 switches the limit off.
    rate_limit_per_minute: int = Field(default=120, ge=0)
    rate_limit_anonymous_per_minute: int = Field(default=30, ge=0)
    # IMAP: requests a minute to one account's server, and how many pass at
    # once. An account's own max_requests_per_minute wins over the rate.
    imap_requests_per_minute: float = Field(default=60.0, gt=0)
    imap_burst: int = Field(default=10, ge=1)
    # IMAP: attempts at a server that does not answer, within one request.
    # After the last the server rests: the first pause in seconds, doubled
    # after each further failure up to the longest.
    imap_attempts: int = Field(default=3, ge=1)
    imap_first_pause: float = Field(default=30.0, gt=0)
    imap_longest_pause: float = Field(default=900.0, gt=0)
    # Sign-in: failures from one client address within the lockout time
    # that lock the address out for that long, in minutes. Wrong API
    # tokens and wrong UI passwords count alike. A user name waits
    # ``sign_in_name_wait`` seconds after as many failures from anywhere.
    sign_in_failures: int = Field(default=10, ge=1)
    sign_in_lockout_minutes: int = Field(default=15, ge=1)
    sign_in_name_wait: int = Field(default=60, ge=1)
    # Password hashes running at once. Each takes 32 MiB.
    password_hashes_at_once: int = Field(default=2, ge=1)
    # UI: hours a session lives without a request, and at most, used or
    # not. Sessions of one user at most: a new one ends the oldest.
    session_idle_hours: float = Field(default=8.0, gt=0)
    session_max_hours: float = Field(default=24.0, gt=0)
    sessions_per_user: int = Field(default=10, ge=1)
    # UI: minutes a secret shown once waits for the page that shows it.
    shown_once_minutes: float = Field(default=5.0, gt=0)
    # Autodiscovery: lookups a minute per user.
    discovery_per_minute: int = Field(default=10, ge=1)
    # The kinds of account that can be connected, a JSON list such as
    # ["imap","jmap","pop3"]. Empty: every kind. Accounts connected before
    # keep working and may sign in again.
    providers: list[str] | None = None
    # OAuth for Microsoft accounts: an app the operator registered in
    # Microsoft Entra ID. Without a client id, the project's app: a public
    # client without a secret (CONCEPT 5.4). The secret from a file (a
    # container secret) or from the environment.
    oauth_microsoft_client_id: str | None = None
    oauth_microsoft_client_secret: SecretStr | None = None
    oauth_microsoft_client_secret_file: Path | None = None
    # Who may sign in: common (personal and work or school accounts),
    # consumers, organizations, or one tenant's id or domain.
    oauth_microsoft_tenant: str = "common"
    # OAuth for Gmail and Google Workspace: a client the operator made in
    # a Google Cloud project (CONCEPT 5.5, docs/GOOGLE.md). The project
    # ships none. Without it, Gmail connects over IMAP with an app
    # password. The secret from a file or from the environment.
    oauth_google_client_id: str | None = None
    oauth_google_client_secret: SecretStr | None = None
    oauth_google_client_secret_file: Path | None = None

    @field_validator("log_level", mode="before")
    @classmethod
    def _lower(cls, value: object) -> object:
        return value.lower() if isinstance(value, str) else value

    @model_validator(mode="after")
    def _consistent(self) -> Self:
        if self.webhook_longest_retry < self.webhook_first_retry:
            raise ValueError(
                "webhook_longest_retry must not be shorter than webhook_first_retry"
            )
        if self.imap_longest_pause < self.imap_first_pause:
            raise ValueError(
                "imap_longest_pause must not be shorter than imap_first_pause"
            )
        microsoft = _named(
            self.oauth_microsoft_client_secret,
            self.oauth_microsoft_client_secret_file,
        )
        if microsoft and not self.oauth_microsoft_client_id:
            # The project's app has no secret: this one belongs to another.
            raise ValueError(
                "a Microsoft client secret needs the client id of its app "
                "in oauth_microsoft_client_id"
            )
        google = _named(
            self.oauth_google_client_secret, self.oauth_google_client_secret_file
        )
        if google != bool(self.oauth_google_client_id):
            raise ValueError(
                "a Google client needs both its id in oauth_google_client_id "
                "and its secret in oauth_google_client_secret or "
                "oauth_google_client_secret_file"
            )
        return self

    def oauth_microsoft_secret(self) -> SecretStr | None:
        """The client secret, from its file if one is named. None for a
        public client, which has none."""
        return _secret(
            self.oauth_microsoft_client_secret,
            self.oauth_microsoft_client_secret_file,
        )

    def oauth_google_secret(self) -> SecretStr | None:
        """The Google client's secret, from its file if one is named."""
        return _secret(
            self.oauth_google_client_secret, self.oauth_google_client_secret_file
        )

    @property
    def database_path(self) -> Path:
        return (self.data_dir / "mailbox.db").resolve()


def _named(secret: SecretStr | None, file: Path | None) -> bool:
    """Whether a secret is set, in the environment or as a file."""
    return bool(secret is not None and secret.get_secret_value()) or file is not None


def _secret(secret: SecretStr | None, file: Path | None) -> SecretStr | None:
    """A secret, from its file if one is named, else from the environment."""
    if file is not None:
        return SecretStr(file.read_text(encoding="utf-8").strip())
    return secret if secret is not None and secret.get_secret_value() else None


Origin = Literal["named", "working directory", "system"]


@dataclass(frozen=True)
class Folders:
    """Where a command reads its settings and keeps its data (CONCEPT 7.4).
    ``env_file`` is read when it exists. ``data`` holds the database unless
    ``MAILBOX_SERVICE_DATA_DIR`` moves it."""

    origin: Origin
    config: Path
    env_file: Path
    data: Path


def folders(env_file: Path | None = None) -> Folders:
    """The folders that apply, first found first: the settings file named
    on purpose, the repository's layout in the working directory where it
    has either folder, else those of the operating system. A file named
    on purpose is ``env_file``, else the one ``MAILBOX_SERVICE_ENV_FILE``
    names."""
    named = system.named_file(env_file, ENV_FILE_VARIABLE)
    if named is not None:
        named = named.resolve()
        return Folders("named", named.parent, named, named.parent / DATA_DIR)
    local = Path(ENV_FILE)
    if local.parent.is_dir() or DATA_DIR.is_dir():
        return Folders("working directory", local.parent, local, DATA_DIR)
    found = system.system_folders(APP)
    return Folders("system", found.config, found.config / ".env", found.data)


def settings_file(env_file: Path | None = None) -> Path | None:
    """The file the settings are read from, None when there is none."""
    found = folders(env_file).env_file
    return found.resolve() if found.is_file() else None


def load_settings(env_file: Path | None = None) -> Settings:
    """The settings of a command. A file named on purpose must exist.
    A relative path in the settings counts from the folder of the settings
    file, so the service finds its data wherever it is started. In the
    repository's layout that is the working directory, as before."""
    where = folders(env_file)
    if where.origin == "named" and not where.env_file.is_file():
        raise FileNotFoundError(f"settings file {where.env_file} not found")
    settings = Settings(_env_file=where.env_file if where.env_file.is_file() else None)
    if where.origin == "working directory":
        return settings
    moved: dict[str, Path] = {
        key: where.config / value
        for key in PATH_SETTINGS
        if isinstance(value := getattr(settings, key), Path) and not value.is_absolute()
    }
    if "data_dir" not in settings.model_fields_set:
        moved["data_dir"] = where.data
    return settings.model_copy(update=moved)
