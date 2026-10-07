"""An account's settings, read: the servers they name and the login there,
as named values.

The settings are a mapping, as the API takes and returns them. An adapter
reads them here once, when it is built. A value it cannot take is refused
as ``settings.<key> must be ...``. What discovery found is turned into
such a mapping by each adapter's ``settings_from``, with ``server_of``.
"""

from __future__ import annotations

import math
from collections.abc import Callable, Mapping
from dataclasses import dataclass
from typing import Any, TypeVar

from ...errors import BadRequestError
from ..models import MailServer, ServerProtocol
from ..protocols import SMTP_PORTS
from .base import ProviderSettings

N = TypeVar("N", int, float)


@dataclass(frozen=True)
class Login:
    """A server the settings name, and the user name to log in with."""

    host: str
    port: int
    security: str  # "tls" or "starttls"
    username: str


@dataclass(frozen=True)
class Host:
    """A server the settings name: its key, such as ``smtp_host``, the
    host, and the port, 0 where none is set."""

    key: str
    host: str
    port: int


def mail_server(
    settings: ProviderSettings, account: str, protocol: str, ports: Mapping[str, int]
) -> Login:
    """The mail server an IMAP or POP3 account logs in to: ``host``,
    ``port``, ``security`` and ``username``. ``account`` names the kind in
    an error, ``ports`` holds the default port per security."""
    host = settings.get("host")
    if not host:
        raise BadRequestError(f"{account} needs settings.host")
    security = encrypted(settings, "security", protocol)
    username = settings.get("username")
    if not username:
        raise BadRequestError(f"{account} needs settings.username")
    return Login(
        host=str(host),
        port=port_of(settings, "port", ports[security]),
        security=security,
        username=str(username),
    )


def smtp_server(settings: ProviderSettings, username: str) -> Login | None:
    """The SMTP server: ``smtp_host``, ``smtp_port``, ``smtp_security`` and
    ``smtp_username``, else ``username``. None without ``smtp_host``."""
    host = settings.get("smtp_host")
    if not host:
        return None
    security = encrypted(settings, "smtp_security", "SMTP")
    return Login(
        host=str(host),
        port=port_of(settings, "smtp_port", SMTP_PORTS[security]),
        security=security,
        username=str(settings.get("smtp_username") or username),
    )


def encrypted(settings: ProviderSettings, key: str, protocol: str) -> str:
    """The security under ``key``: ``tls`` (the default) or ``starttls``.
    Anything else, a connection without encryption too, is refused."""
    security = str(settings.get(key, "tls"))
    if security not in ("tls", "starttls"):
        raise BadRequestError(
            f"settings.{key} must be 'tls' or 'starttls': "
            f"{protocol} without encryption is not supported"
        )
    return security


def port_of(settings: ProviderSettings, key: str, default: int) -> int:
    """A port from the settings: a whole number from 1 to 65535."""
    return _number(
        settings, key, default, int, lambda p: 1 <= p <= 65535, "a port from 1 to 65535"
    )


def rate_of(settings: ProviderSettings, key: str, default: float) -> float:
    """A rate per minute from the settings: a number above 0."""
    return _number(
        settings, key, default, float, lambda r: 0 < r < math.inf, "a number above 0"
    )


def _number(
    settings: ProviderSettings,
    key: str,
    default: N,
    read: Callable[[Any], N],
    valid: Callable[[N], bool],
    must_be: str,
) -> N:
    """The number under ``key``, ``default`` when it is not set. A value
    ``read`` cannot take, a truth value or one not ``valid`` is refused."""
    value = settings.get(key)
    if value is None or value == "":
        return default
    try:
        number = None if isinstance(value, bool) else read(value)
    except (TypeError, ValueError):
        number = None
    if number is None or not valid(number):
        raise BadRequestError(f"settings.{key} must be {must_be}")
    return number


def hosts_in(settings: Mapping[str, object]) -> list[Host]:
    """Every server the settings name: ``host`` with ``port``, ``smtp_host``
    with ``smtp_port``, and any other ``*_host``."""
    found = []
    for key, value in settings.items():
        if not (key == "host" or key.endswith("_host")):
            continue
        if not isinstance(value, str) or not value:
            continue
        port = settings.get(key[: -len("host")] + "port")
        found.append(Host(key, value, port if isinstance(port, int) else 0))
    return found


def server_of(servers: list[MailServer], protocol: ServerProtocol) -> MailServer | None:
    """The first of the discovered ``servers`` that speaks ``protocol``."""
    return next((s for s in servers if s.protocol is protocol), None)
