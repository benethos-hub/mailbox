"""Reaching an IMAP server: the sessions, the settings of an account
from discovered servers, and a probe of a server without a login."""

from __future__ import annotations

from collections.abc import Callable

from .... import __version__
from ...models import CredentialKind, MailServer, ServerProtocol
from ...protocols import IMAP_PORTS, ImapSession, Server
from ..mailserver import PROBE_TIMEOUT, capabilities_of, login_settings
from ..settings import server_of

SessionFactory = Callable[[Server], ImapSession]

CLIENT_ID = ("benethos-mailbox-service", __version__)


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
    return {
        **login_settings(imap, servers, email),
        "auth": "xoauth2" if credential is CredentialKind.OAUTH else "password",
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
    """The capabilities of an IMAP server, read without logging in."""
    return await capabilities_of(
        session_factory, "IMAP", IMAP_PORTS, host, port, security, address
    )
