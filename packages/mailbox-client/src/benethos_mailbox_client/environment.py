"""Where the service is and the token that opens it: read from the
environment or given, and checked before a client is made. Nothing here
sends anything."""

from __future__ import annotations

import ipaddress
import os
from dataclasses import dataclass

import httpx

from .errors import ConfigurationError

DEFAULT_URL = "http://127.0.0.1:8080"
URL_ENV = "MAILBOX_SERVICE_URL"
TOKEN_ENV = "MAILBOX_SERVICE_TOKEN"
# Allows http to a host other than this machine, e.g. between containers.
ALLOW_HTTP_ENV = "MAILBOX_SERVICE_ALLOW_HTTP"


def service_url() -> str:
    """The service's address: ``MAILBOX_SERVICE_URL``, else the default."""
    return (os.environ.get(URL_ENV) or DEFAULT_URL).rstrip("/")


@dataclass(frozen=True, slots=True)
class Environment:
    """What the environment says about the service, read at one moment:
    its address, the token, and whether http may go to another machine.
    Unchecked: a client checks it when it is made."""

    url: str
    token: str
    allow_http: bool


def from_environment() -> Environment:
    """``MAILBOX_SERVICE_URL``, ``MAILBOX_SERVICE_TOKEN`` and
    ``MAILBOX_SERVICE_ALLOW_HTTP`` as they are now. A client made without
    them reads them here. A program that makes clients for a long time,
    such as the MCP server, reads them once."""
    allowed = os.environ.get(ALLOW_HTTP_ENV, "").strip().lower()
    return Environment(
        url=service_url(),
        token=os.environ.get(TOKEN_ENV, ""),
        allow_http=allowed in ("1", "true", "yes"),
    )


@dataclass(frozen=True, slots=True)
class Connection:
    """Where the service is and the token that opens it, checked."""

    base_url: str
    headers: dict[str, str]


def connection(
    base_url: str | None, token: str | None, allow_http: bool | None
) -> Connection:
    """Raises without a token, and when the URL would carry the token
    unencrypted to another machine, unless ``allow_http`` (else
    ``MAILBOX_SERVICE_ALLOW_HTTP``) says so."""
    found = from_environment()
    url = (base_url or found.url).rstrip("/")
    if allow_http is None:
        allow_http = found.allow_http
    _check_url(url, allow_http)
    token = token if token is not None else found.token
    if not token:
        raise ConfigurationError(
            f"{TOKEN_ENV} is not set. Make a token on your user's page in "
            "the service's UI and set it."
        )
    return Connection(url, {"Authorization": f"Bearer {token}"})


def _check_url(url: str, allow_http: bool) -> None:
    """https anywhere, http to this machine, or anywhere when allowed."""
    try:
        parts = httpx.URL(url)
    except httpx.InvalidURL:
        raise ConfigurationError(f"{URL_ENV} is not a URL: {url}") from None
    if parts.scheme == "https" and parts.host:
        return
    if parts.scheme != "http" or not parts.host:
        raise ConfigurationError(f"{URL_ENV} must be an http or https URL: {url}")
    if allow_http or _loopback(parts.host):
        return
    raise ConfigurationError(
        f"{URL_ENV} is http to {parts.host}, so the token would travel "
        f"unencrypted. Use https, or set {ALLOW_HTTP_ENV}=1 for a network you "
        "trust, such as between containers."
    )


def _loopback(host: str) -> bool:
    if host.lower() == "localhost":
        return True
    try:
        return ipaddress.ip_address(host).is_loopback
    except ValueError:
        return False
