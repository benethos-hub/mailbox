"""Settings, resolved from the environment and an optional ``.env`` file,
and the folders a command reads them from and keeps its data in."""

from __future__ import annotations

import re
from pathlib import Path
from typing import Literal, Self
from urllib.parse import SplitResult, urlsplit

from pydantic import Field, SecretStr, field_validator, model_validator

# Named apart from folders() below.
from benethos_mailbox_common.paths import folders as system
from benethos_mailbox_common.settings import files

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
    "database_password_file",
    "database_ca_file",
)
# The address of a database server, without its password.
DATABASE_URL_FORM = "postgresql://<role>@<host>:<port>/<database>"
# A role, and the schema named after it, as the server takes it unquoted.
_PLAIN_NAME = re.compile(r"[a-z_][a-z0-9_]{0,62}")


class Settings(files.FileSettings):
    """Every setting of the REST service. Prefix ``MAILBOX_SERVICE_``."""

    model_config = {
        "env_prefix": "MAILBOX_SERVICE_",
        "env_file": ENV_FILE,
        "populate_by_name": True,
    }

    host: str = "127.0.0.1"
    port: int = Field(default=8080, ge=1, le=65535)
    # The address people reach the service at, e.g. https://mail.example.org
    # behind a proxy. Builds the OAuth redirect address, which the provider
    # must know. It also fixes the origin and the RP ID of passkeys
    # (docs/mailbox-service/AUTHENTICATION.md). Empty: taken from each request.
    public_url: str | None = None
    # Behind a reverse proxy: the proxy's address (or several, separated by
    # commas, or "*"), whose X-Forwarded-For and X-Forwarded-Proto headers
    # are believed. They give the client address that the sign-in throttle
    # and the request limit count and the scheme the session cookie's
    # Secure flag follows. The host the OAuth redirect is built from
    # without a public URL is the Host header as the proxy passes it on.
    # Empty: only a proxy on 127.0.0.1 is believed.
    forwarded_allow_ips: str | None = None
    # As uvicorn names them, in any case.
    log_level: Literal["critical", "error", "warning", "info", "debug", "trace"] = (
        "info"
    )
    # Each line of the log on stderr as text, or as one JSON object for a
    # log collector. The log page shows text either way.
    log_format: Literal["text", "json"] = "text"
    # Where the database lives. Without it the data folder that `paths`
    # names. A relative path counts from the folder of the settings file.
    data_dir: Path = DATA_DIR
    # "sqlite" keeps the records in a file in the data folder, "postgres"
    # in a schema on a PostgreSQL server, which the settings database_*
    # name. "memory" keeps nothing across restarts. For tests and trying
    # things out.
    storage: Literal["sqlite", "postgres", "memory"] = "sqlite"
    # PostgreSQL: the server as postgresql://<role>@<host>:<port>/<database>,
    # without a password. The schema is named after the role.
    database_url: str | None = None
    # PostgreSQL: the file holding the password of the role.
    database_password_file: Path | None = None
    # PostgreSQL: "verify" talks to a host other than this one only over
    # TLS with a checked certificate and name. "off" goes without TLS,
    # for a private network, and the start says so.
    database_tls: Literal["verify", "off"] = "verify"
    # PostgreSQL: the certificates of the authorities the server's is
    # checked against. Without it those of the system.
    database_ca_file: Path | None = None
    # PostgreSQL: seconds serve waits for the database at start.
    database_start_wait: int = Field(default=30, ge=0)
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
    # Sync worker: accounts watched at once. An IMAP watcher holds a thread
    # of its own while it waits in IDLE, outside the pool that answers
    # requests. Further accounts are polled only.
    sync_watchers: int = Field(default=50, ge=1)
    # The figures of the service for Prometheus at GET /v1/metrics, for a
    # token with the right get_metrics. Off, the route answers 404.
    metrics: bool = True
    # Threads: the messages a thread lists at most, the newest.
    thread_messages: int = Field(default=500, ge=1)
    # Threads the service keeps itself (IMAP): of the References of a
    # message, the last ones kept to find its thread.
    thread_references: int = Field(default=20, ge=0)
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
    # The outbox: hours its attempts go on after a job is due. Then it
    # fails, and its draft stays.
    outbox_retry_hours: int = Field(default=48, ge=1)
    # Seconds a link to an attachment holds, at most: share_attachment may
    # ask for fewer.
    link_seconds: int = Field(default=120, ge=1)
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
    # a Google Cloud project (CONCEPT 5.5, docs/mailbox-service/GOOGLE.md). The project
    # ships none. Without it, Gmail connects over IMAP with an app
    # password. The secret from a file or from the environment.
    oauth_google_client_id: str | None = None
    oauth_google_client_secret: SecretStr | None = None
    oauth_google_client_secret_file: Path | None = None

    @field_validator("log_level", "log_format", mode="before")
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
        if self.storage == "postgres":
            _database_settings(self.database_url, self.database_password_file)
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

    def check_database_server(self) -> str:
        """The address of the database server, held to its rules whatever
        the storage says: for a move to it or from it. ValueError names the
        rule, never what was given."""
        _database_settings(self.database_url, self.database_password_file)
        return str(self.database_url)

    def database_password(self) -> SecretStr:
        """The password of the role on the database server, read from its
        file now. Empty without one."""
        if self.database_password_file is None:
            return SecretStr("")
        return SecretStr(files.secret_file(self.database_password_file))

    @property
    def database_path(self) -> Path:
        return (self.data_dir / "mailbox.db").resolve()

    def database_name(self) -> str:
        """The database for a line: the path of its file, or the address
        of its server, which holds no password."""
        if self.storage == "postgres" and self.database_url:
            parts = urlsplit(self.database_url)
            host = parts.netloc.rsplit("@", 1)[-1]
            return f"{parts.scheme}://{parts.username}@{host}{parts.path}"
        return str(self.database_path)


def database_url_parts(url: str) -> SplitResult:
    """The parts of ``database_url``, which the settings checked."""
    return urlsplit(url)


def _database_settings(url: str | None, password_file: Path | None) -> None:
    """The rules of storage = postgres. A message names the rule, never
    what was given, which may hold a password."""
    if not url or password_file is None:
        raise ValueError(
            "storage postgres needs database_url and database_password_file"
        )
    if _empty(password_file):
        raise ValueError("database_password_file names an empty file")
    parts = urlsplit(url)
    if parts.scheme != "postgresql":
        raise ValueError(f"database_url must have the form {DATABASE_URL_FORM}")
    if parts.password is not None:
        raise ValueError(
            "database_url must not hold a password: name the file that holds"
            " it in database_password_file"
        )
    if parts.query or parts.fragment or "?" in url or "#" in url:
        raise ValueError(
            "database_url must not hold a query or a fragment: the password"
            " comes from database_password_file, TLS from database_tls"
        )
    try:
        port = parts.port
    except ValueError:
        port = None
    role = parts.username or ""
    database = parts.path.removeprefix("/")
    if not (role and parts.hostname and database and "/" not in database) or (
        port is None and ":" in parts.netloc.rsplit("@", 1)[-1]
    ):
        raise ValueError(f"database_url must have the form {DATABASE_URL_FORM}")
    if not _PLAIN_NAME.fullmatch(role):
        raise ValueError(
            "the role in database_url names the schema too: lower case"
            " letters, digits and underscores"
        )


def _empty(path: Path) -> bool:
    """Whether the file holds nothing but blanks. One that cannot be read
    is not judged here: opening the database says why."""
    try:
        return not files.secret_file(path)
    except OSError:
        return False


def _named(secret: SecretStr | None, file: Path | None) -> bool:
    """Whether a secret is set, in the environment or as a file."""
    return bool(secret is not None and secret.get_secret_value()) or file is not None


def _secret(secret: SecretStr | None, file: Path | None) -> SecretStr | None:
    """A secret, from its file if one is named, else from the environment."""
    if file is not None:
        return SecretStr(files.secret_file(file))
    return secret if secret is not None and secret.get_secret_value() else None


def folders(env_file: Path | None = None) -> system.Folders:
    """The folders that apply, first found first (CONCEPT 7.4): the
    settings file named on purpose, ``env_file`` or the one
    ``MAILBOX_SERVICE_ENV_FILE`` names, the repository's layout in the
    working directory where it has either folder, else those of the
    operating system. ``data`` holds the database unless
    ``MAILBOX_SERVICE_DATA_DIR`` moves it."""
    return system.program_folders(
        APP, env_file, ENV_FILE_VARIABLE, Path(ENV_FILE), DATA_DIR
    )


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
    settings = files.load(Settings, where.env_file)
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
