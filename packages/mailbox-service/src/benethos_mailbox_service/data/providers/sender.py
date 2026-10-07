"""Sending for adapters without sending of their own, such as IMAP and POP3.

An adapter holds one ``SmtpSender``, or none when the account has no SMTP
server. The sender reads the ``smtp_*`` settings, logs in with the account's
credential and goes through the account's ``Guard``. What the adapter does
after a send, such as a copy in the sent folder, stays with the adapter.
"""

from __future__ import annotations

from collections.abc import Callable

from ..models import MailServer, ServerProtocol
from ..protocols import Pick, Server, SmtpLogin, SmtpSession
from .base import ProviderSettings
from .guard import Guard
from .settings import server_of, smtp_server

SmtpFactory = Callable[[Server], SmtpSession]


def smtp_settings(servers: list[MailServer], username: str) -> dict[str, str | int]:
    """The ``smtp_*`` settings of the SMTP server among the discovered
    ``servers``, empty without one. Its user name only where it differs
    from the account's ``username``."""
    smtp = server_of(servers, ServerProtocol.SMTP)
    if smtp is None:
        return {}
    found: dict[str, str | int] = {
        "smtp_host": smtp.host,
        "smtp_port": smtp.port,
        "smtp_security": str(smtp.security),
    }
    if smtp.username and smtp.username != username:
        found["smtp_username"] = smtp.username
    return found


class SmtpSender:
    def __init__(
        self,
        session: SmtpSession,
        username: str,
        auth: str,
        secret: Callable[[], str],
        guard: Guard,
    ) -> None:
        self._session = session
        self._username = username
        self._auth = auth
        self._secret = secret
        self._guard = guard

    @classmethod
    def from_settings(
        cls,
        settings: ProviderSettings,
        username: str,
        auth: str,
        secret: Callable[[], str],
        guard: Guard,
        factory: SmtpFactory = SmtpSession,
        pick: Pick | None = None,
    ) -> SmtpSender | None:
        """From ``smtp_host``, ``smtp_port``, ``smtp_security`` and
        ``smtp_username`` (else ``username``). None when the account has no
        SMTP server: it cannot send."""
        login = smtp_server(settings, username)
        if login is None:
            return None
        server = Server(
            host=login.host, port=login.port, security=login.security, pick=pick
        )
        return cls(factory(server), login.username, auth, secret, guard)

    def send(self, raw: bytes, sender: str, recipients: list[str]) -> list[str]:
        """Send, blocking. The recipients the server refused."""
        # The same credential as the mailbox: no new attempt until it changes.
        return self._guard.once(
            lambda: self._session.send(self._login(), sender, recipients, raw)
        )

    def verify(self) -> None:
        """Log in and out, blocking."""
        self._guard.once(lambda: self._session.verify(self._login()))

    def _login(self) -> SmtpLogin:
        """The credential, decrypted for this one use."""
        return SmtpLogin(self._username, self._secret(), self._auth)
