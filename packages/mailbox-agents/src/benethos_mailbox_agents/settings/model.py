"""The settings of one agent and how they are read: the class, its
checks, and the TLS context of an own CA. ``settings`` offers them."""

from __future__ import annotations

import re
import ssl
from pathlib import Path
from typing import Annotated, Any, Literal

from pydantic import Field, SecretStr, ValidationError, field_validator, model_validator

from benethos_mailbox_common.log import redact
from benethos_mailbox_common.settings import files

from ..errors import ConfigError, describe_invalid

# The form a keyword must have, MAILBOX_AGENTS_KEYWORD and an agent's
# default_keyword alike: lower case letters, digits and dashes, as
# agent-invoice. No $, which IMAP registers with meanings such as $Junk, no
# capitals, no control character, and so one IMAP atom.
KEYWORD_FORM = re.compile(r"[a-z0-9][a-z0-9-]*")

PREFIX = "MAILBOX_AGENTS_"

# Where the .env file is looked for when none is named, relative to the
# working directory. The example beside it lists every setting.
DEFAULT_ENV_FILE = Path("config/benethos-mailbox-agents/.env")

Stage = Literal["shadow", "keyword", "full"]


class Settings(files.FileSettings):
    """The settings of one process, which runs one agent. A name the
    agents do not know is left alone, as the base has it."""

    model_config = {
        "env_prefix": PREFIX,
        "env_file_encoding": "utf-8",
        "frozen": True,
    }

    # --- upstreams ---------------------------------------------------------
    service_url: str | None = None
    service_token: SecretStr | None = None
    service_token_file: Path | None = None
    # The client refuses http to another machine, since the token would
    # travel unencrypted. Between two containers on one network that is
    # the deployment's decision.
    service_allow_http: bool = False
    gateway_url: str | None = None
    gateway_allow_http: bool = False
    gateway_key: SecretStr | None = None
    gateway_key_file: Path | None = None
    gateway_timeout_seconds: float = Field(default=120.0, gt=0)
    model: str | None = None
    # The certificates of the authorities https to both upstreams trusts,
    # in place of the roots of certifi, for a service or gateway with a
    # certificate of an own CA. SSL_CERT_FILE is not read.
    ca_file: Path | None = None

    # --- what the agent works on and how far it may go ----------------------
    accounts: Annotated[list[str], files.NoDecode] = Field(default_factory=list)
    stage: Stage = "shadow"
    keyword: str | None = None

    # --- the loop ------------------------------------------------------------
    poll_seconds: float = Field(default=60.0, gt=0)
    tick_seconds: float = Field(default=900.0, gt=0)
    max_attempts: int = Field(default=5, ge=1)
    backoff_ceiling_seconds: float = Field(default=3600.0, gt=0)
    backfill_days: int = Field(default=7, ge=0)

    # --- state, metrics, log ---------------------------------------------------
    data_dir: Path = Path("data")
    prompt_retention_days: int = Field(default=0, ge=0)
    metrics_port: int = Field(default=0, ge=0, le=65535)
    log_level: Literal["DEBUG", "INFO", "WARNING", "ERROR"] = "INFO"

    # --- invoices, docs/mailbox-agents/concept/agent-invoices.md ----------------------
    invoices_folders: Annotated[list[str], files.NoDecode] = Field(default_factory=list)
    invoices_subfolder: str | None = None
    invoices_inbox_folder: str | None = None

    # --- awaiting_reply, docs/mailbox-agents/concept/agent-awaiting-reply.md ----------
    reply_days: int = Field(default=3, ge=1)

    # --- inquiries, docs/mailbox-agents/concept/agent-inquiries.md --------------------
    inquiries_patterns_file: Path | None = None

    # --- sorting, docs/mailbox-agents/concept/agent-sorting.md ------------------------
    sorting_file: Path | None = None

    @field_validator("accounts", "invoices_folders", mode="before")
    @classmethod
    def _split_list(cls, value: Any) -> Any:
        """``a,b`` in the environment, a list when built in code."""
        if isinstance(value, str):
            return [part.strip() for part in value.split(",") if part.strip()]
        return value

    @field_validator(
        "ca_file",
        "keyword",
        "sorting_file",
        "inquiries_patterns_file",
        "service_token_file",
        "gateway_key_file",
        mode="before",
    )
    @classmethod
    def _empty_is_unset(cls, value: Any) -> Any:
        """An empty line, as ``.env.example`` holds, is not set: a path
        would be the folder ``.``, a keyword one that is refused."""
        return None if value == "" else value

    @field_validator("ca_file")
    @classmethod
    def _readable_ca(cls, value: Path | None) -> Path | None:
        """Read at the start: a missing file, or one without a certificate,
        stops it, not the first call."""
        if value is not None:
            _context(value)
        return value

    @field_validator("log_level", mode="before")
    @classmethod
    def _upper(cls, value: Any) -> Any:
        return value.upper() if isinstance(value, str) else value

    @field_validator("keyword")
    @classmethod
    def _one_word(cls, value: str | None) -> str | None:
        """A keyword is lower case letters, digits and dashes, as the
        agents' own: one IMAP atom without a meaning of its own."""
        if value is not None and not KEYWORD_FORM.fullmatch(value):
            raise ValueError(
                "a keyword is lower case letters, digits and dashes, "
                "such as agent-invoice"
            )
        return value

    @model_validator(mode="after")
    def _secrets_from_files(self) -> Settings:
        """Read a secret named by its ``_FILE`` setting, and register both
        secrets so no error text carries them. An empty value counts as not
        set, as the empty line ``.env.example`` holds. A file may start
        with the mark of UTF-8 an editor puts there. A secret is printable
        ASCII, as a header of HTTP carries it: any other is refused by the
        name of its setting, never with its value."""
        for name in ("service_token", "gateway_key"):
            setting = f"{PREFIX}{name.upper()}"
            given: SecretStr | None = getattr(self, name)
            if given is not None and not given.get_secret_value():
                object.__setattr__(self, name, None)
            path: Path | None = getattr(self, f"{name}_file")
            if getattr(self, name) is None and path is not None:
                setting += "_FILE"
                try:
                    text = path.read_text(encoding="utf-8-sig").strip()
                except (OSError, ValueError) as exc:
                    raise ValueError(
                        f"{setting} cannot be read ({type(exc).__name__})"
                    ) from None
                object.__setattr__(self, name, SecretStr(text) if text else None)
            secret: SecretStr | None = getattr(self, name)
            if secret is not None:
                value = secret.get_secret_value()
                if not (value.isascii() and value.isprintable()):
                    raise ValueError(
                        f"{setting} holds a character that is not printable ASCII"
                    )
                redact.note(value)
        return self

    def missing(self, names: tuple[str, ...]) -> list[str]:
        """The settings among ``names`` that are not set, as their full
        environment names."""
        return [f"{PREFIX}{name.upper()}" for name in names if not getattr(self, name)]

    def ssl_context(self) -> ssl.SSLContext | None:
        """The TLS context for both upstreams when ``CA_FILE`` names one,
        trusting the authorities of that file only. None keeps the roots
        of certifi."""
        return None if self.ca_file is None else _context(self.ca_file)

    def secret(self, name: Literal["service_token", "gateway_key"]) -> str:
        """The value of a secret, or a :class:`ConfigError` naming it."""
        found: SecretStr | None = getattr(self, name)
        if found is None:
            raise ConfigError(f"{PREFIX}{name.upper()} is not set")
        return found.get_secret_value()


def _context(path: Path) -> ssl.SSLContext:
    try:
        return ssl.create_default_context(cafile=str(path))
    except (OSError, ssl.SSLError):
        raise ValueError("a readable file of PEM certificates") from None


def load_settings(env_file: Path | None = None, **overrides: Any) -> Settings:
    """The settings from the environment and ``env_file``, the default
    file when none is named and it exists.

    A wrong setting becomes a :class:`ConfigError` that names the setting
    and the rule, never the value, which may be a secret.
    """
    path = env_file if env_file is not None else DEFAULT_ENV_FILE
    if env_file is not None and not path.is_file():
        raise ConfigError(f"the settings file {path.name} does not exist")
    try:
        return files.load(Settings, path, **overrides)
    except ValidationError as exc:
        problems = describe_invalid(
            exc, lambda place: f"{PREFIX}{place.upper() or 'SETTINGS'}"
        )
        raise ConfigError(f"wrong settings: {problems}") from None
