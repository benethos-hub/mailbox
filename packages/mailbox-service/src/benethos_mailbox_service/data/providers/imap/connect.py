"""Reaching an IMAP server: the sessions, the settings of an account
from discovered servers, and a probe of a server without a login."""

from __future__ import annotations

from collections.abc import Callable

import anyio

from .... import __version__
from ....errors import BadRequestError
from ...models import CredentialKind, MailServer, ServerProtocol
from ...protocols import IMAP_PORTS, ImapSession, Server
from ..sender import smtp_settings
from ..settings import server_of

SessionFactory = Callable[[Server], ImapSession]

CLIENT_ID = ("benethos-mailbox-service", __version__)

PROBE_TIMEOUT = 10.0


def default_session(server: Server) -> ImapSession:
    return ImapSession(server, client_id=CLIENT_ID)


def settings_from(
    servers: list[MailServer], credential: CredentialKind, email: str
) -> dict[str, str | int | bool]:
    """The settings of an IMAP account from discovered servers, as
    ``ImapProvider`` reads them. Empty without an IMAP server."""
    imap = server_of(servers, ServerProtocol.IMAP)
    if imap is None:
        return {}
    username = imap.username or email
    return {
        "host": imap.host,
        "port": imap.port,
        "security": str(imap.security),
        "username": username,
        "auth": "xoauth2" if credential is CredentialKind.OAUTH else "password",
        **smtp_settings(servers, username),
    }


def probe_session(server: Server) -> ImapSession:
    return ImapSession(server, timeout=PROBE_TIMEOUT)


async def probe(
    host: str,
    port: int,
    security: str,
    address: str | None = None,
    session_factory: SessionFactory = probe_session,
) -> frozenset[str]:
    """The capabilities of an IMAP server, read without logging in. With
    ``address``, the connection goes there, the address just checked."""
    if security not in IMAP_PORTS:
        raise BadRequestError("IMAP without encryption is not supported")
    pick = (lambda _host, _port: address) if address is not None else None
    session = session_factory(
        Server(host=host, port=port, security=security, pick=pick)
    )
    return await anyio.to_thread.run_sync(session.read_capabilities)
