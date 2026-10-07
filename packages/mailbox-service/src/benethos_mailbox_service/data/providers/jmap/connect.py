"""Reaching a JMAP server: the settings of an account read, and made from
discovered servers."""

from __future__ import annotations

from dataclasses import dataclass

from ....errors import BadRequestError
from ...models import CredentialKind, MailServer, ServerProtocol
from ...protocols import jmap
from ..base import ProviderSettings
from ..settings import port_of, server_of


@dataclass(frozen=True)
class JmapSettings:
    """Where the session resource is, and how the account signs in:
    ``password`` with ``username``, or ``token`` without one."""

    host: str
    port: int
    path: str
    auth: str
    username: str


def read_settings(settings: ProviderSettings) -> JmapSettings:
    """``host``, ``port``, ``path``, ``auth`` and ``username``. JMAP runs
    over HTTPS, so ``security`` can only be ``tls``."""
    host = settings.get("host")
    if not host:
        raise BadRequestError("a JMAP account needs settings.host")
    if str(settings.get("security", "tls")) != "tls":
        raise BadRequestError("settings.security must be 'tls': JMAP runs over HTTPS")
    path = str(settings.get("path") or jmap.DEFAULT_PATH)
    if not _is_path(path):
        raise BadRequestError("settings.path must be a path such as /.well-known/jmap")
    auth = str(settings.get("auth", "password"))
    if auth not in ("password", "token"):
        raise BadRequestError("settings.auth must be 'password' or 'token'")
    username = settings.get("username")
    if auth == "password" and not username:
        raise BadRequestError("a JMAP account with a password needs settings.username")
    return JmapSettings(
        host=str(host),
        port=port_of(settings, "port", jmap.DEFAULT_PORT),
        path=path,
        auth=auth,
        username=str(username or ""),
    )


def settings_from(
    servers: list[MailServer], credential: CredentialKind, email: str
) -> dict[str, str | int | bool]:
    """The settings of a JMAP account from discovered servers, as
    ``read_settings`` reads them. Empty without a JMAP server."""
    server = server_of(servers, ServerProtocol.JMAP)
    if server is None or credential is CredentialKind.OAUTH:
        return {}
    settings: dict[str, str | int | bool] = {
        "host": server.host,
        "port": server.port,
        "path": server.path or jmap.DEFAULT_PATH,
    }
    if credential is CredentialKind.API_TOKEN:
        settings["auth"] = "token"
    else:
        settings["username"] = server.username or email
    return settings


def _is_path(path: str) -> bool:
    """A path on the server, with a query perhaps: printable ASCII without
    spaces, and no fragment."""
    return (
        path.startswith("/")
        and path.isascii()
        and path.isprintable()
        and " " not in path
        and "#" not in path
    )
