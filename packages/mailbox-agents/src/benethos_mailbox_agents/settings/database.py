"""The state on a PostgreSQL server, as the settings name it: the rules
of ``STORAGE=postgres``, and the server they name. A message names the
rule, never what was given, which may hold a password."""

from __future__ import annotations

from collections.abc import Sequence
from pathlib import Path
from typing import Literal

from benethos_mailbox_common.log import redact
from benethos_mailbox_common.settings import files
from benethos_mailbox_common.storage import names, server_place, server_url

from ..errors import ConfigError


def server_problem(
    *,
    storage: str,
    url: str | None,
    password_file: Path | None,
    readers: Sequence[str],
    retention_days: int,
) -> str | None:
    """What is wrong with the settings of a state on a server, None when
    nothing, or when the state is a file."""
    if storage != "postgres":
        return None
    if not url or password_file is None:
        return "storage postgres needs database_url and database_password_file"
    found = server_url.url_problem(url)
    if found is not None:
        return found
    if not all(names.is_plain_name(role) for role in readers):
        return (
            "database_readers names roles: lower case letters, digits and underscores"
        )
    if retention_days:
        return (
            "prompt_retention_days keeps the text of model calls, which a state"
            " on a server does not hold: set it to 0 with storage postgres"
        )
    return None


def shown_database(url: str) -> str:
    """Where a state on the server ``url`` names lies, ``url`` without a
    problem, for a line of a command: never a password."""
    named = server_url.server_at(url, "")
    return (
        f"the database {named.database} on {named.host}:{named.port},"
        f" schema {named.schema_name}"
    )


def server_of(
    url: str | None,
    path: Path | None,
    *,
    tls: Literal["verify", "off"],
    ca_file: Path | None,
    setting: str,
) -> server_place.Server:
    """The server ``url`` names, with the password of its role read now
    from the file at ``path`` and kept from every log line. ``setting``
    names the file in an error."""
    if url is None or path is None:
        raise ConfigError("storage postgres needs database_url and its password file")
    try:
        password = files.secret_file(path)
    except (OSError, ValueError) as exc:
        raise ConfigError(f"{setting} cannot be read ({type(exc).__name__})") from None
    if not password:
        raise ConfigError(f"{setting} names an empty file")
    redact.note(password)
    return server_url.server_at(url, password, tls=tls, ca_file=ca_file)
