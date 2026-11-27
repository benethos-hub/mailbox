"""The address of a database server in a setting: its form, what is
wrong with one, and the server and role it names."""

from __future__ import annotations

from pathlib import Path
from typing import Literal
from urllib.parse import urlsplit

from . import names
from .server_place import Server

# The address of a database server, without its password.
URL_FORM = "postgresql://<role>@<host>:<port>/<database>"


def url_problem(url: str, setting: str = "database_url") -> str | None:
    """What is wrong with ``url`` as the address of a database server, in
    the form of ``URL_FORM``, named by ``setting``: None when nothing. A
    message names the rule, never what was given, which may hold a
    password."""
    parts = urlsplit(url)
    if parts.scheme != "postgresql":
        return f"{setting} must have the form {URL_FORM}"
    if parts.password is not None:
        return (
            f"{setting} must not hold a password: name the file that holds"
            " it in database_password_file"
        )
    if parts.query or parts.fragment or "?" in url or "#" in url:
        return (
            f"{setting} must not hold a query or a fragment: the password"
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
        return f"{setting} must have the form {URL_FORM}"
    if not names.is_plain_name(role):
        return (
            f"the role in {setting} names the schema too: lower case"
            " letters, digits and underscores"
        )
    return None


def server_at(
    url: str,
    password: str,
    *,
    tls: Literal["verify", "off"] = "verify",
    ca_file: Path | None = None,
) -> Server:
    """The server and role ``url`` names, ``url`` in the form of
    ``URL_FORM`` with no problem, signed in with ``password``."""
    parts = urlsplit(url)
    return Server(
        host=parts.hostname or "",
        port=parts.port or 5432,
        database=parts.path.removeprefix("/"),
        role=parts.username or "",
        password=password,
        tls=tls,
        ca_file=ca_file,
    )
